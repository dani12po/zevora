"""Workspace planning, task orchestration, and provider completion."""
import json
from pathlib import Path
from time import perf_counter

from fastapi import HTTPException
from agent.core.attachments import attachment_context, process_attachment
from agent.core.execution import AgentAction, ProjectAgentExecutor
from agent.core.planning import parse_action_plan, planning_system_prompt, public_action
from agent.core.project_index import format_project_context, project_context
from agent.memory.store import Store, model_cache_signature
from agent.routing.quality_gate import validate
from agent.security.redaction import redact
from agent.storage.context_economy import build_context as build_economic_context

from api.helpers import (
    _attempt_record,
    _AGENTIC_LOG_INSTRUCTION,
    _action_receipt,
    _estimated_cost,
    _fallback_failure_message,
    _model_metadata,
    _parse_agentic_response,
    _requires_workspace_agent,
    _usage_tokens,
)
from api.schemas import AgentActionRequest, PlanRequest, TaskRequest

import main

async def _provider_completion(candidate, prompt: str, system: str,
                               images: list[dict] | None = None):
    provider = main.get_provider(candidate.provider)
    if images:
        return await provider.complete_multimodal(
            prompt, images, system, candidate.model_id or ''
        )
    if candidate.model_id and hasattr(provider, 'complete_for_model'):
        return await provider.complete_for_model(prompt, system, candidate.model_id)
    return await provider.complete(prompt, system)

async def plan_agent_actions(body: PlanRequest):
    project = main.workspace_manager.get(body.project_id)
    if not project:
        raise HTTPException(404, {
            'code': 'PROJECT_NOT_FOUND', 'message': 'Selected project was not found.'
        })
    root = Path(project['path']).resolve()
    context = project_context(root, body.prompt)
    main.store.replace_project_files(str(root), context['rows'])
    base_prompt = (
        f'User request:\n{redact(body.prompt)}\n\n'
        f'{format_project_context(context)}'
    )
    inspection_tools = {
        'list_directory', 'read_file', 'search_files', 'file_exists', 'get_file_info',
    }
    max_iterations = max(1, min(12, main.settings.max_agent_iterations))
    max_tool_calls = max(1, min(30, main.settings.max_agent_tool_calls))
    timeout_seconds = max(1, min(300, main.settings.agent_timeout_seconds))
    started = perf_counter()
    gateway = main.LocalMCPGateway(root)
    enabled_tools = gateway.enabled_tools()
    pending_actions: list[AgentAction] = []
    inspection_count = 0
    observations: list[dict] = []
    seen_plans: set[str] = set()
    completion = None

    for iteration in range(max_iterations):
        if perf_counter() - started >= timeout_seconds:
            raise HTTPException(409, {
                'code': 'AGENT_LOOP_LIMIT',
                'message': 'Planning timed out before a stable action plan was produced.',
                'iteration': iteration, 'tool_calls': inspection_count,
                'last_tool_result': observations[-1] if observations else None,
                'intervention_required': True,
            })
        observation_context = ''
        if observations:
            observation_context = (
                '\n\nAuthoritative tool observations from this planning run:\n'
                + json.dumps(observations, ensure_ascii=True)[-20_000:]
                + '\nReturn the next necessary actions only. Do not repeat completed inspections.'
            )
        completion = await main._cloud_completion(
            base_prompt + observation_context,
            planning_system_prompt(
                max_tool_calls - inspection_count, enabled_tools
            ), 'json',
            lambda response: parse_action_plan(
                response, max_tool_calls - inspection_count, enabled_tools
            ),
            require_native_tools=False,
            routing_prompt=body.prompt,
        )
        actions = parse_action_plan(
            completion['response'], max_tool_calls - inspection_count, enabled_tools
        )
        signature = json.dumps(
            [public_action(action) for action in actions], sort_keys=True
        )
        if signature in seen_plans:
            raise HTTPException(409, {
                'code': 'AGENT_LOOP_LIMIT',
                'message': 'The provider repeated an already completed action plan.',
                'iteration': iteration + 1, 'tool_calls': inspection_count,
                'last_tool_result': observations[-1] if observations else None,
                'intervention_required': True,
            })
        seen_plans.add(signature)

        if not actions:
            break
        inspections = [action for action in actions if action.tool in inspection_tools]
        deferred = [action for action in actions if action.tool not in inspection_tools]
        if deferred:
            pending_actions.extend(actions)
            break
        for action in inspections:
            if inspection_count >= max_tool_calls:
                raise HTTPException(409, {
                    'code': 'AGENT_LOOP_LIMIT',
                    'message': 'Planning reached the maximum number of tool calls.',
                    'iteration': iteration + 1, 'tool_calls': inspection_count,
                    'last_tool_result': observations[-1] if observations else None,
                    'intervention_required': True,
                })
            result = gateway.execute(action.tool, action.arguments, approved=False)
            inspection_count += 1
            observations.append({
                'tool': action.tool, 'arguments': action.arguments,
                'ok': result.ok, 'output': result.output,
            })
    else:
        raise HTTPException(409, {
            'code': 'AGENT_LOOP_LIMIT',
            'message': 'Planning reached the maximum number of reasoning iterations.',
            'iteration': max_iterations, 'tool_calls': inspection_count,
            'last_tool_result': observations[-1] if observations else None,
            'intervention_required': True,
        })

    return {
        'ok': True,
        'needs_tools': bool(pending_actions),
        'actions': [public_action(action) for action in pending_actions],
        'provider': completion['provider'] if completion else None,
        'model': completion['model'] if completion else None,
        'estimated_cost': completion['estimated_cost'] if completion else 0.0,
        'iterations': len(seen_plans),
        'tool_calls': len(pending_actions),
        'inspection_tool_calls': inspection_count,
        'project_files': [item['path'] for item in context['files']],
    }

async def task(body: TaskRequest):
    started = perf_counter()
    prompt = redact(body.prompt)
    progress_id = body.progress_id

    def progress(stage: str, status: str = 'completed', detail: str = '') -> None:
        main._progress_update(progress_id, stage, detail, status)

    progress('UNDERSTAND', detail='Request accepted and being classified')
    mode = body.mode.strip().lower()
    if mode not in {'auto', 'local', 'provider', 'model'}:
        raise HTTPException(400, {
            'code': 'INVALID_ROUTING_OVERRIDE',
            'message': 'mode must be auto, local, provider, or model',
        })
    # Conversation intent: ask = pure Q&A (never plans or executes workspace
    # actions), coding = force the workspace agent flow, auto = classify.
    chat_mode = (body.chat_mode or 'auto').strip().lower()
    if chat_mode not in {'auto', 'ask', 'coding'}:
        chat_mode = 'auto'
    ask_mode = chat_mode == 'ask'
    force_workspace = chat_mode == 'coding'
    if ask_mode and body.actions:
        body = body.model_copy(update={'actions': []})
    requested_provider = body.provider.strip().lower() if body.provider else None
    requested_model = body.model.strip() if body.model else None
    if mode == 'provider' and not requested_provider:
        raise HTTPException(400, {
            'code': 'INVALID_ROUTING_OVERRIDE', 'message': 'provider mode requires provider',
        })
    if mode == 'model' and (not requested_provider or not requested_model):
        raise HTTPException(400, {
            'code': 'INVALID_ROUTING_OVERRIDE',
            'message': 'model mode requires both provider and model',
        })
    try:
        progress('ATTACHMENTS', 'running', 'Processing attachments')
        processed_attachments = [
            process_attachment(item.name, item.media_type, item.data_base64)
            for item in body.attachments
        ]
    except ValueError as error:
        raise HTTPException(400, {'code': 'INVALID_ATTACHMENT', 'message': str(error)})
    attachment_metadata = [item.metadata() for item in processed_attachments]
    progress('ATTACHMENTS', detail=f'Prepared {len(processed_attachments)} attachment(s)')
    images = [
        {'media_type': item.media_type, 'data_base64': item.image_base64}
        for item in processed_attachments if item.kind == 'image'
    ]
    attachment_reference = attachment_context(processed_attachments)
    attachment_hash = ''.join(item.content_hash for item in processed_attachments)
    project_hash = ''
    project_reference = ''
    project_files_used: list[str] = []
    project_discovery = None
    agent_trace = None
    agentic_log: list[str] | None = None
    root = None
    if not ask_mode and not body.project and (body.actions or force_workspace or _requires_workspace_agent(prompt)):
        raise HTTPException(400, {
            'code': 'PROJECT_REQUIRED',
            'message': (
                'Select or open the target project folder before asking ZEVORA to '
                'read, create, edit, or run files. Tool access is scoped to that folder.'
            ),
        })
    if body.project:
        progress('INSPECT', 'running', 'Inspecting selected project')
        root = Path(body.project).resolve()
        if not root.is_dir():
            raise HTTPException(400, 'Project directory not found')
        registered = next((
            project for project in main.workspace_manager.projects()
            if Path(project['path']).resolve() == root
        ), None)
        if not registered:
            raise HTTPException(403, {
                'code': 'PROJECT_NOT_REGISTERED',
                'message': 'Load the project into the workspace before running tasks in it.',
            })

        # The browser is only a client.  Keep planning on the gateway so every
        # client gets the same agent behavior, including API/CLI callers.
        # Ask mode never plans actions; coding mode always plans them.
        if not ask_mode and not body.actions and (force_workspace or _requires_workspace_agent(prompt)):
            progress('PLAN', 'running', 'Planning workspace actions')
            project = main.workspace_manager.load(root)
            plan = await plan_agent_actions(PlanRequest(
                prompt=body.prompt, project_id=project['id'],
            ))
            body.actions = [AgentActionRequest(
                tool=item['tool'], arguments=item.get('arguments', {}),
                purpose=item.get('purpose', ''), approved=False,
            ) for item in plan.get('actions', [])]
            progress('PLAN', detail=f'Prepared {len(body.actions)} workspace action(s)')

        progress('RETRIEVE', 'running', 'Reading project context')
        context = project_context(root, prompt)
        main.store.replace_project_files(str(root), context['rows'])
        project_hash = context['context_hash']
        project_reference = format_project_context(context)
        project_files_used = [item['path'] for item in context['files']]
        project_discovery = context['discovery']
        progress('RETRIEVE', detail=f'Loaded {len(project_files_used)} project file reference(s)')
        if body.actions:
            project = main.workspace_manager.load(root)
            executor = ProjectAgentExecutor(root, preferences=project.get('permissions'))
            agent_trace = executor.execute(
                prompt,
                [AgentAction(**action.model_dump()) for action in body.actions],
                project_files_used,
                progress_callback=progress,
                event_callback=lambda event: main._workflow_record(
                    progress_id,
                    stage=event.get('stage', 'EXECUTION'),
                    event=event.get('event', 'tool_completed'),
                    status=event.get('status', 'completed'),
                    title=event.get('title', 'Agent activity'),
                    message=event.get('message', ''),
                    data=event.get('data'),
                ),
            )
            if agent_trace.pending_approvals:
                raise HTTPException(403, {
                    'code': 'APPROVAL_REQUIRED',
                    'message': 'Explicit approval is required before executing requested actions.',
                    'pending_approvals': agent_trace.pending_approvals,
                    'agent_trace': agent_trace.to_dict(),
                })
            failed_actions = [
                item for item in agent_trace.observations if not item.get('ok')
            ]
            if failed_actions:
                raise HTTPException(409, {
                    'code': 'ACTION_FAILED',
                    'message': 'One or more workspace actions failed. No success was reported.',
                    'failed_actions': failed_actions,
                    'agent_trace': agent_trace.to_dict(),
                })
            # Workspace actions may have changed project state; rebuild authoritative context.
            progress('RETRIEVE', 'running', 'Refreshing context after workspace changes')
            context = project_context(root, prompt)
            main.store.replace_project_files(str(root), context['rows'])
            project_hash = context['context_hash']
            project_reference = format_project_context(context)
            project_files_used = [item['path'] for item in context['files']]
            project_discovery = context['discovery']

            mutation_tools = {
                'create_file', 'write_file', 'edit_file', 'delete_file',
                'move_file', 'copy_file',
            }
            if any(action.tool in mutation_tools for action in body.actions):
                progress('FINAL_RESPONSE', 'running', 'Assembling the workspace result')
                agent_trace.stage('FINAL_RESPONSE', detail={
                    'source': 'authoritative_tool_results',
                })
                elapsed = int((perf_counter() - started) * 1000)
                task_type = main.router.classify(prompt)
                response = _action_receipt(root, agent_trace)
                main.intelligence_engine.extract_knowledge(
                    prompt, response, task_type.value, 'local', 'mcp-tools', body.project
                )
                main.store.add_memory('conversation', prompt, body.project, task_type.value)
                return {
                    'response': response, 'provider': 'local', 'model': 'mcp-tools',
                    'task_type': task_type.value, 'skills_used': [], 'route': 'LOCAL',
                    'reason': 'TOOLS_EXECUTED',
                    'tools': [action.tool for action in body.actions],
                    'estimated_cost': 0.0, 'quality_score': 1.0, 'cache_hit': False,
                    'execution_ms': elapsed, 'context_hash': project_hash,
                    'project_files': project_files_used,
                    'project_discovery': project_discovery,
                    'context_status': 'RETRIEVAL_ENRICHED',
                    'flow': main._flow_status(
                        workspace='SELECTED', discovery='COMPLETE', context='RETRIEVAL_ENRICHED',
                        route='LOCAL', action='EXECUTED',
                        verification=(
                            'COMPLETE' if agent_trace.verified is True else
                            'FAILED' if agent_trace.verified is False else 'SKIPPED'
                        ),
                        knowledge='EXTRACTED',
                    ),
                    'attachments': attachment_metadata,
                    'agent_trace': agent_trace.to_dict(),
                    'agentic_log': None,
                    'workflow': main._progress_snapshot(progress_id),
                }

    context_hash = Store.key(project_hash, attachment_hash) if attachment_hash else project_hash
    progress('REASON', detail='Preparing the response context')
    # Action-bearing and explicitly routed requests are never replayed through Auto cache entries.
    cache_sig = model_cache_signature()
    cached = None if body.actions or mode != 'auto' else main.store.get_cache(prompt, context_hash, cache_sig)
    if cached:
        progress('FINAL_RESPONSE', detail='Using a verified local response')
        with main.store.connection() as conn:
            conn.execute(
                "INSERT INTO usage_events(provider,model,task_type,cache_hit,created_at) VALUES(?,?,?,?,datetime('now'))",
                (cached['provider'], cached['model'], cached['task_type'], 1),
            )
        return {
            'response': cached['response'], 'provider': cached['provider'],
            'model': cached['model'], 'task_type': cached['task_type'],
            'route': 'CACHE', 'reason': 'EXACT_CACHE_HIT', 'tools': [], 'cache_hit': True,
            'context_hash': context_hash, 'project_files': project_files_used,
            'project_discovery': project_discovery,
            'context_status': 'CACHE_SUFFICIENT',
            'flow': main._flow_status(
                workspace='SELECTED' if body.project else 'NOT_SELECTED',
                discovery='COMPLETE' if body.project else 'SKIPPED',
                context='CACHE_SUFFICIENT', route='CACHE', action='SKIPPED',
                verification='SKIPPED', knowledge='RETRIEVED',
            ),
            'attachments': attachment_metadata,
            'fallback_trace': [{'source': 'local', 'status': 'success', 'kind': 'exact_cache'}],
            'agentic_log': None,
            'workflow': main._progress_snapshot(progress_id),
        }

    routing_prompt = f'{prompt}\n[image attachment]' if images else prompt
    task_type = main.router.classify(routing_prompt)
    progress('REASON', detail='Classifying the request and preparing skills')
    skill_context, skills_used = main.basic_skills.context_for(prompt)
    dynamic_skill_context, dynamic_skills = main.skill_registry.context_for(
        prompt, capabilities=set(task_type.value.split(',')), max_chars=8_000
    )
    if dynamic_skill_context:
        skill_context = '\n\n'.join(filter(None, (skill_context, dynamic_skill_context)))
        skills_used = list(dict.fromkeys([*skills_used, *dynamic_skills]))

    local_context = main.intelligence_engine.build_context(prompt, task_type.value, body.project, main.store)
    observation_context = ''
    if agent_trace and agent_trace.observations:
        observation_context = 'Tool observations:\n' + json.dumps(
            agent_trace.observations, ensure_ascii=True
        )[:20_000]
    context_parts = [
        part for part in (
            local_context, project_reference, attachment_reference, observation_context
        ) if part
    ]
    context_economy = build_economic_context(
        context_parts,
        max_tokens=main.settings.context_max_tokens,
        compression_enabled=main.settings.context_compression_enabled,
    )
    combined_context = context_economy.text
    context_status = 'RETRIEVAL_ENRICHED' if combined_context else 'ROUTER_REQUIRED'

    system_prompt = body.system + '\n\n' + _AGENTIC_LOG_INSTRUCTION + (
        '\n\nUse the following approved reference skill as guidance. '
        'Never bypass the agent permission system.\n' + skill_context if skill_context else ''
    ) + (f"\n\nContext:\n{combined_context}" if combined_context else "")

    # Explicit selection narrows the same capability-aware router pool; it never bypasses routing checks.
    progress('ROUTE', 'running', 'Selecting a provider and model')
    available_models, candidates = await main._routing_candidates(
        routing_prompt, context_economy.compressed_tokens,
        mode, requested_provider, requested_model,
    )
    if mode != 'auto' and not available_models:
        raise HTTPException(400, {
            'code': 'ROUTING_OVERRIDE_UNAVAILABLE',
            'message': 'The selected provider or model is not available in the model registry.',
        })
    fallback_trace = []
    if not candidates:
        raise HTTPException(503, {
            'code': 'AI_EXECUTION_ERROR',
            'message': _fallback_failure_message(fallback_trace),
            'fallback_trace': fallback_trace,
        })

    response = usage = decision = None
    provider_name = selected_model = None
    selected_metadata = None
    attempt_started = perf_counter()
    for candidate in candidates[:max(1, main.settings.routing_max_attempts)]:
        progress('GENERATE', 'running', f'Generating response with {candidate.provider}')
        await main._emit_stream_event({
            'type': 'attempt_start', **_attempt_record(candidate, 'running'),
        })
        candidate_started = perf_counter()
        try:
            candidate_response, candidate_usage = await main._provider_completion(
                candidate, prompt, system_prompt, images
            )
            clean_candidate, candidate_log = _parse_agentic_response(candidate_response)
            if not validate(clean_candidate)['accepted']:
                raise RuntimeError('Quality gate rejected response')
            response, usage, decision = clean_candidate, candidate_usage, candidate
            agentic_log = candidate_log
            provider_name, selected_model = candidate.provider, candidate.model_id
            selected_metadata = _model_metadata(
                available_models, provider_name, selected_model
            )
            attempt_started = candidate_started
            success_record = _attempt_record(candidate, 'success')
            fallback_trace.append(success_record)
            await main._emit_stream_event({'type': 'attempt_result', **success_record})
            break
        except Exception as error:
            latency = int((perf_counter() - candidate_started) * 1000)
            main.store.add_routing_experience(
                candidate.route.value, candidate.provider, candidate.model_id or '',
                ','.join(candidate.task_type), False, 0.0, latency, candidate.tools,
            )
            failure_record = _attempt_record(candidate, 'failed', error)
            fallback_trace.append(failure_record)
            await main._emit_stream_event({'type': 'attempt_result', **failure_record})

    if response is None or usage is None or decision is None:
        progress('GENERATE', 'failed', 'No provider could complete the response')
        raise HTTPException(503, {
            'code': 'AI_EXECUTION_ERROR',
            'message': _fallback_failure_message(fallback_trace),
            'fallback_trace': fallback_trace,
        })

    # Default model fallback for providers that don't expose model_id via discovery
    cloud_defaults = {
        'local': main.settings.active_local_model_profile.model_id,
        'openai': main.settings.openai_model, 'gemini': main.settings.gemini_model,
        'anthropic': main.settings.anthropic_model, 'xai': '', 'nvidia': '', 'deepseek': '',
    }
    response = redact(response)
    if agentic_log:
        agentic_log = [redact(item) for item in agentic_log]
    model = selected_model or cloud_defaults.get(provider_name, '')
    input_tokens, output_tokens = _usage_tokens(usage)
    context_metrics = {
        **context_economy.metrics(),
        'provider_tokens': input_tokens,
    }
    estimated_cost = _estimated_cost(selected_metadata, input_tokens, output_tokens)
    quality = validate(response)['quality_score']

    main.intelligence_engine.extract_knowledge(prompt, response, task_type.value, provider_name, model, body.project)

    if not body.actions and mode == 'auto':
        main.store.put_cache(
            prompt, response, provider_name, model, task_type.value,
            body.project, context_hash=context_hash, model_signature=cache_sig,
            ttl_hours=main.settings.cache_default_ttl_hours,
        )
    main.store.add_memory('conversation', prompt, body.project, task_type.value)
    elapsed = int((perf_counter() - started) * 1000)
    attempt_latency = int((perf_counter() - attempt_started) * 1000)
    verified_outcome = bool(quality >= .5 and (not agent_trace or agent_trace.verified is not False))
    main.store.add_context_metrics(task_type.value, provider_name, model, context_metrics)
    compact_experience = {
        'task_class': task_type.value,
        'route': decision.route.value.lower(),
        'result': 'success',
        'provider': provider_name,
        'model': model,
        'skill_ids': skills_used,
        'confidence': quality,
        'execution_time_ms': elapsed,
        'verified': verified_outcome,
    }
    main.store.add_structured_experience(compact_experience)
    evolution_result = main.evolution_engine.observe(compact_experience, quality)

    with main.store.connection() as conn:
        conn.execute(
            "INSERT INTO usage_events(provider,model,task_type,input_tokens,output_tokens,estimated_cost,cache_hit,created_at) VALUES(?,?,?,?,?,?,?,datetime('now'))",
            (provider_name, model, task_type.value,
             input_tokens, output_tokens, estimated_cost, 0),
        )
        conn.execute(
            "INSERT INTO experiences(task,provider,model,outcome,execution_ms,metadata_json,created_at) VALUES(?,?,?,?,?,?,datetime('now'))",
            (prompt, provider_name, model, 'success', elapsed, '{}'),
        )

    main.store.add_routing_experience(
        decision.route.value, provider_name, model, ','.join(decision.task_type),
        True, quality, attempt_latency, decision.tools,
    )
    if agent_trace:
        if agent_trace.verified is False and main.settings.max_repair_attempts > 0:
            agent_trace.stage(
                'FIX', status='not_executed',
                detail='Verification failed; a new approved repair action is required.',
            )
            agent_trace.stage('VERIFY_AGAIN', status='skipped')
        else:
            agent_trace.stage('FIX', status='skipped')
            agent_trace.stage('VERIFY_AGAIN', status='skipped')
        agent_trace.stage('FINAL_RESPONSE')

    progress('FINAL_RESPONSE', detail='Response ready')
    return {
        'response': response, 'provider': provider_name, 'model': model,
        'task_type': task_type.value, 'skills_used': skills_used,
        'route': decision.route.value, 'reason': decision.reason,
        'tools': decision.tools, 'estimated_cost': estimated_cost,
        'quality_score': quality, 'cache_hit': False, 'execution_ms': elapsed,
        'context_hash': context_hash, 'context_economy': context_metrics,
        'evolution': evolution_result,
        'project_files': project_files_used,
        'project_discovery': project_discovery,
        'context_status': context_status,
        'flow': main._flow_status(
            workspace='SELECTED' if body.project else 'NOT_SELECTED',
            discovery='COMPLETE' if body.project else 'SKIPPED',
            context=context_status, route=decision.route.value,
            action='EXECUTED' if agent_trace else 'SKIPPED',
            verification=(
                'COMPLETE' if agent_trace and agent_trace.verified is True else
                'FAILED' if agent_trace and agent_trace.verified is False else 'SKIPPED'
            ),
            knowledge='EXTRACTED',
        ),
        'attachments': attachment_metadata, 'fallback_trace': fallback_trace,
        'agent_trace': agent_trace.to_dict() if agent_trace else None,
        'agentic_log': agentic_log,
        'workflow': main._progress_snapshot(progress_id),
    }
