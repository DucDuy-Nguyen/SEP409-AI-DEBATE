"""Test khong ghi audit log ra dia (get_settings doc bien nay truoc .env). Test cua audit log tu dat duong dan rieng."""
import os

os.environ["EVAL_AUDIT_LOG_PATH"] = ""
