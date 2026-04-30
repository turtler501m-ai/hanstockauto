const escapeHtml = (value) => {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
};

const setStatus = (message, ok = false) => {
    const banner = document.getElementById('status-banner');
    banner.hidden = false;
    banner.className = `status-banner ${ok ? 'ok' : ''}`;
    banner.textContent = message;
};

const setButtonBusy = (id, busy) => {
    const button = document.getElementById(id);
    if (button) {
        button.disabled = busy;
    }
};

async function fetchJson(url) {
    const response = await fetch(url);
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.detail || `요청 실패: ${response.status}`);
    }
    return data;
}

async function postJson(url, payload = {}) {
    const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.detail || `요청 실패: ${response.status}`);
    }
    return data;
}

function buildEnvControl(field) {
    const key = escapeHtml(field.key);
    const label = escapeHtml(field.label || field.key);
    const value = escapeHtml(field.value || '');
    const hint = field.hint || (field.secret ? '민감정보가 그대로 표시됩니다.' : '');

    if (field.type === 'bool') {
        const selected = String(field.value || '').toLowerCase() === 'true';
        return `
            <div class="env-field">
                <label for="env-${key}">${label}</label>
                <select id="env-${key}" data-env-key="${key}" data-original="${escapeHtml(field.value || '')}">
                    <option value="true" ${selected ? 'selected' : ''}>true</option>
                    <option value="false" ${!selected ? 'selected' : ''}>false</option>
                </select>
                <small>${hint}</small>
            </div>
        `;
    }

    if (field.type === 'select') {
        const options = (field.options || []).map((option) => {
            const selected = String(field.value || '') === String(option);
            return `<option value="${escapeHtml(option)}" ${selected ? 'selected' : ''}>${escapeHtml(option)}</option>`;
        }).join('');
        return `
            <div class="env-field">
                <label for="env-${key}">${label}</label>
                <select id="env-${key}" data-env-key="${key}" data-original="${escapeHtml(field.value || '')}">
                    ${options}
                </select>
                <small>${hint}</small>
            </div>
        `;
    }

    const inputType = field.type === 'secret' ? 'text' : (field.type === 'int' || field.type === 'float' ? 'number' : 'text');
    const step = field.type === 'float' ? ' step="any"' : '';
    const placeholder = field.secret ? '값 입력' : '';
    return `
        <div class="env-field">
            <label for="env-${key}">${label}</label>
            <input id="env-${key}" type="${inputType}"${step} value="${value}" placeholder="${placeholder}"
                data-env-key="${key}" data-original="${value}" autocomplete="off">
            <small>${hint}</small>
        </div>
    `;
}

async function renderEnvSettings() {
    try {
        const data = await fetchJson('/api/env');
        document.getElementById('env-grid').innerHTML = (data.fields || []).map(buildEnvControl).join('');
        document.getElementById('env-meta').textContent = `${data.path || '.env'} · 저장 후 서버 재시작 필요`;
    } catch (err) {
        setStatus(`환경설정 불러오기 실패: ${err.message}`);
    }
}

async function saveEnvSettings(event) {
    event.preventDefault();
    const values = {};
    document.querySelectorAll('[data-env-key]').forEach((input) => {
        const key = input.dataset.envKey;
        const original = input.dataset.original || '';
        const value = input.value;
        if (value !== original) {
            values[key] = value;
        }
    });

    if (!Object.keys(values).length) {
        setStatus('변경된 환경설정이 없습니다.', true);
        return;
    }

    setButtonBusy('btn-env-save', true);
    try {
        const result = await postJson('/api/env', { values });
        await renderEnvSettings();
        setStatus(`환경설정을 저장했습니다: ${result.updated.join(', ')}. 서버를 재시작해야 적용됩니다.`, true);
    } catch (err) {
        setStatus(`환경설정 저장 실패: ${err.message}`);
    } finally {
        setButtonBusy('btn-env-save', false);
    }
}

document.getElementById('env-form').addEventListener('submit', saveEnvSettings);
document.getElementById('btn-env-reload').addEventListener('click', renderEnvSettings);
renderEnvSettings();
