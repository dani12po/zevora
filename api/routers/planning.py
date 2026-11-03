"""Agent planning endpoints."""
import json
from pathlib import Path
from time import perf_counter

from fastapi import HTTPException
from agent.core.execution import AgentAction
from agent.core.planning import parse_action_plan, planning_system_prompt, public_action
from agent.core.project_index import format_project_context, project_context
from agent.security.redaction import redact

from main import app
from api.schemas import PlanRequest

import main

@app.post('/api/agent/plan')
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
