import sys
import json
import re

DESTRUCTIVE_PATTERNS = [
    (
        r"docker\s+(system|volume|container|image)\s+prune",
        "Comando de limpieza global de Docker detectado (prune). Requiere confirmación humana."
    ),
    (
        r"(rm|del|erase|remove-item)\b.*flota\.db",
        "Intento de eliminar la base de datos protegida flota.db. Requiere confirmación humana."
    ),
    (
        r"git\s+(reset\s+--hard|push\s+.*--force|push\s+-f\b|clean\s+-[fd])",
        "Comando destructivo de Git detectado (reset --hard / push --force / clean). Requiere confirmación humana."
    ),
    (
        r"drop\s+table\b|truncate\s+table\b",
        "Operación SQL destructiva (DROP/TRUNCATE TABLE) detectada. Requiere confirmación humana."
    ),
]


def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            print(json.dumps({"decision": "allow"}))
            return

        payload = json.loads(raw_input)
        tool_call = payload.get("toolCall", {})
        args = tool_call.get("args", {}) or {}
        cmd = str(args.get("CommandLine", ""))

        for pattern, reason in DESTRUCTIVE_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE):
                print(json.dumps({
                    "decision": "force_ask",
                    "reason": reason
                }))
                return

        print(json.dumps({"decision": "allow"}))
    except Exception:
        # En caso de error de parseo no bloquear la herramienta, delegar en política estándar
        print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()

