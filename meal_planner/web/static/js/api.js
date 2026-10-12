// JSON requests to the local backend. Errors carry the server's issue list.

export class ApiError extends Error {
  constructor(message, issues = []) {
    super(message);
    this.issues = issues;
  }
}

let busyCount = 0;

function setBusy(on, text) {
  busyCount += on ? 1 : -1;
  const box = document.getElementById('busy');
  if (on) document.getElementById('busy_text').textContent = text;
  box.hidden = busyCount <= 0;
}

// `busyText` shows a blocking "working" overlay for slow calls (Claude, solver).
export async function api(method, url, body, busyText) {
  if (busyText) setBusy(true, busyText);
  try {
    const options = { method, headers: {} };
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    const response = await fetch(url, options);
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new ApiError((data && data.error) || `请求失败（HTTP ${response.status}）`, (data && data.issues) || []);
    }
    return data;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError('无法连接到本地服务，请确认 app.py 仍在运行', [String(err)]);
  } finally {
    if (busyText) setBusy(false);
  }
}

export const get = (url) => api('GET', url);
export const post = (url, body, busyText) => api('POST', url, body ?? {}, busyText);
export const put = (url, body) => api('PUT', url, body);
export const del = (url) => api('DELETE', url);
