"""Exports for normal Streamlit and static-hosted browser Python."""
import base64
from html import escape
import json
from pathlib import Path
import sys
import streamlit as st
import streamlit.components.v1 as components


def download_file(label, data, filename, mime='text/csv'):
    if sys.platform != 'emscripten':
        st.download_button(label, data, file_name=filename, mime=mime, use_container_width=True)
        return
    context_file = Path(__file__).parent / 'web_context.json'
    if context_file.exists():
        url = json.loads(context_file.read_text()).get('downloads', {}).get(filename)
        if url:
            st.link_button(label, url, use_container_width=True)
            return
    raw = data.encode('utf-8') if isinstance(data, str) else data
    payload = json.dumps({'data': base64.b64encode(raw).decode('ascii'), 'name': filename, 'mime': mime}).replace('</', '<\\/')
    components.html('''<!doctype html><html><head><meta charset="utf-8"><style>
body{margin:0}button{width:100%;padding:11px 16px;border:1px solid #d9e4df;border-radius:10px;background:white;color:#19654d;font:600 14px system-ui;cursor:pointer}button:hover{background:#edf7f1}button:focus-visible{outline:2px solid #147d62;outline-offset:-3px}
</style></head><body><button id="export">'''+escape(label)+'''</button><script>
const f='''+payload+''';document.getElementById('export').onclick=()=>{const b=Uint8Array.from(atob(f.data),c=>c.charCodeAt(0));const u=URL.createObjectURL(new Blob([b],{type:f.mime}));const a=document.createElement('a');a.href=u;a.download=f.name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),5000);};
</script></body></html>''',height=48,scrolling=False)
