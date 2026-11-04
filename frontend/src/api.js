import {demoReply} from './demo';
export const demoMode = import.meta.env.VITE_DEMO_MODE !== 'false';
const base = import.meta.env.VITE_API_BASE_URL || '';
export async function askAgent({sessionId, message, messages, signal}) {
  if (demoMode) {
    await new Promise((resolve,reject)=>{ const timer=setTimeout(resolve,700); signal?.addEventListener('abort',()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'))},{once:true}); });
    return demoReply(message, messages);
  }
  const res = await fetch(`${base}/api/chat`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({sessionId, message}), signal,
  });
  if(!res.ok) throw new Error(`Assistant request failed (HTTP ${res.status}).`);
  const data = await res.json();
  // Expected: {text, tools:[{name,detail,status}],result:{type:'prospects',customers:[],messages:[]}}
  if(typeof data.text !== 'string') throw new Error('Unexpected API response: text is missing.');
  return data;
}
