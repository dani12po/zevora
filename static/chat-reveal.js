import {renderMarkdown} from './markdown.js?v=20260818-12';

const activeReveals = new Set();

export function cancelReveals() {
  [...activeReveals].forEach(reveal => reveal.skip());
}

export function revealText(bubbleElement, fullText, {speed = 18, onComplete} = {}) {
  const body = document.createElement('div');
  body.className = 'message-body is-revealing';
  body.setAttribute('aria-busy', 'true');
  bubbleElement.append(body);
  let index = 0;
  let timer = null;
  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    if (timer) window.clearTimeout(timer);
    activeReveals.delete(controller);
    body.classList.remove('is-revealing');
    body.removeAttribute('aria-busy');
    body.innerHTML = renderMarkdown(fullText);
    onComplete?.(body);
  };
  const step = () => {
    if (finished) return;
    index = Math.min(fullText.length, index + Math.max(3, Math.ceil(fullText.length / 180)));
    body.textContent = fullText.slice(0, index);
    if (index >= fullText.length) finish();
    else timer = window.setTimeout(step, speed);
  };
  const controller = {skip: finish};
  activeReveals.add(controller);
  bubbleElement.addEventListener('click', controller.skip, {once:true});
  step();
  return controller;
}

document.addEventListener('click', event => {
  if (!event.target.closest('.message-bubble')) cancelReveals();
});
document.addEventListener('scroll', cancelReveals, {passive:true, capture:true});
