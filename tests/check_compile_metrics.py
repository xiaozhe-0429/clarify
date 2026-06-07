"""检查 compile 端点 metrics 记录。"""
from fastapi.testclient import TestClient
from clarify.api import app
client = TestClient(app)

resp1 = client.post('/v1/compile', json={'template_name': 'default.j2', 'answers': {'role': 'test', 'question': 'hi', 'language': 'zh'}})
assert resp1.status_code == 200, f"success compile failed: {resp1.status_code}"

resp2 = client.post('/v1/compile', json={'template_name': 'nonexistent.j2', 'answers': {}})
assert resp2.status_code in (400, 500), f"fail compile returned: {resp2.status_code}"

resp3 = client.get('/v1/metrics')
assert 'compile_template_success_total' in resp3.text

# Prometheus label 格式是 {key="val",key2="val2"} 连在一起，用正则安全匹配
import re
assert re.search(r'compile_template_success_total\{[^}]*status="success"', resp3.text), "success counter not found in metrics"
assert re.search(r'compile_template_success_total\{[^}]*status="failure"', resp3.text), "failure counter not found in metrics"

# 也检查 missing vars
assert re.search(r'compile_template_missing_vars_total\{[^}]*template_name="default\.j2"', resp3.text), "missing vars counter not found"

print("OK")
