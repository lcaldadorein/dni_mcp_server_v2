"""
Cliente MCP – kyoe-consultas
Uso:
    python client.py comisarias --provincia 28 --localidad 28079
    python client.py cita --tipo D --id 12345678Z
    python client.py alta --tipo X --id 12345678Z
    python client.py anular --tipo X --id 12345678Z
    python client.py modificar --tipo X --id 12345678Z --comisaria 0002
    python client.py sms --to +34612345678 --mensaje "Hola desde la POC"
    python client.py crear-codigo
"""

import argparse
import json
import threading
import time
import httpx

MCP_SSE  = "http://localhost:8000/sse"
MCP_POST = "http://localhost:8000/messages/"
PETICION = "CLI-TEST-001"


# ──────────────────────────────────────────────
# MCP session
# ──────────────────────────────────────────────
class MCPClient:
    def __init__(self):
        self.session_id = None
        self.responses  = {}
        self._ready     = threading.Event()
        self._lock      = threading.Lock()
        self._thread    = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            print("✗ No se pudo conectar al servidor MCP en localhost:8000")
            raise SystemExit(1)

    def _listen(self):
        with httpx.Client(timeout=None) as client:
            with client.stream("GET", MCP_SSE) as r:
                for line in r.iter_lines():
                    # El servidor envía el session_id en una línea de evento SSE:
                    # "event: endpoint" seguido de "data: /messages/?session_id=<uuid>"
                    # Solo lo aceptamos si parece un UUID real (sin espacios, longitud razonable)
                    if "session_id=" in line and self.session_id is None:
                        raw = line.split("session_id=")[-1].strip()
                        # Validación mínima: debe parecer un UUID hex (sin espacios, 32+ chars)
                        candidate = raw.split("&")[0].split(" ")[0]
                        if len(candidate) >= 32 and candidate.replace("-", "").isalnum():
                            self.session_id = candidate
                            self._ready.set()
                    elif line.startswith("data:") and self.session_id:
                        try:
                            data = json.loads(line[5:].strip())
                            rid  = data.get("id")
                            if rid is not None:
                                with self._lock:
                                    self.responses[rid] = data
                        except Exception:
                            pass

    def _wait_response(self, rpc_id, timeout=6.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if rpc_id in self.responses:
                    return self.responses.pop(rpc_id)
            time.sleep(0.1)
        return None

    def call(self, method, params, rpc_id):
        body = {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}
        httpx.post(f"{MCP_POST}?session_id={self.session_id}", json=body, timeout=5)
        return self._wait_response(rpc_id)

    def initialize(self):
        # Espera explícita de la respuesta de initialize antes de retornar
        resp = self.call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "kyoe-cli", "version": "1.0"},
        }, rpc_id=0)
        if resp is None:
            print("⚠ initialize sin respuesta")

    def tool(self, name, arguments, rpc_id=1):
        return self.call("tools/call", {"name": name, "arguments": arguments}, rpc_id=rpc_id)


# ──────────────────────────────────────────────
# Renderers
# ──────────────────────────────────────────────

def render_comisarias(data: dict):
    info = data.get("comisarias", {})
    print(json.dumps(info, indent=2, ensure_ascii=False))

def render_cita(data: dict):
    cita = data.get("cita", {})
    if isinstance(cita, str):
        print(cita)
    else:
        print(json.dumps(cita, indent=2, ensure_ascii=False))

def render_resultado(data):
    if isinstance(data, str):
        print(data)
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def render_error(code: str, message: str):
    print(f"✗ Error [{code}]: {message}")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Cliente MCP kyoe-consultas")
    sub    = parser.add_subparsers(dest="cmd", required=True)

    p_com = sub.add_parser("comisarias", help="Consultar comisarías")
    p_com.add_argument("--provincia", type=int, required=True, help="Código provincia (ej. 28)")
    p_com.add_argument("--localidad", type=int, required=True, help="Código localidad (ej. 28079)")
    p_com.add_argument("--peticion",  default=PETICION)

    p_cit = sub.add_parser("cita", help="Consultar cita DNI/NIE/pasaporte")
    p_cit.add_argument("--tipo", required=True, choices=["D","N","P"], help="D=DNI  N=NIE  P=Pasaporte")
    p_cit.add_argument("--id",   required=True, help="Número de documento (ej. 12345678Z)")
    p_cit.add_argument("--peticion", default=PETICION)

    p_alta = sub.add_parser("alta", help="Dar de alta una cita DNIe/pasaporte")
    p_alta.add_argument("--tipo", required=True, choices=["X","D"], help="X=NIE  D=DNI")
    p_alta.add_argument("--id",   required=True, help="Número de documento (ej. 12345678Z)")
    p_alta.add_argument("--peticion",   default=PETICION)
    p_alta.add_argument("--accion",     default="", help="idAccion (opcional)")
    p_alta.add_argument("--tramite",    default="", help="idTramite (opcional)")
    p_alta.add_argument("--comisaria",  default="", help="idComisaria (opcional)")
    p_alta.add_argument("--movil",      default="", help="idMovil (opcional)")

    p_anu = sub.add_parser("anular", help="Anular una cita DNIe/pasaporte")
    p_anu.add_argument("--tipo", required=True, choices=["X","D"], help="X=NIE  D=DNI")
    p_anu.add_argument("--id",   required=True, help="Número de documento (ej. 12345678Z)")
    p_anu.add_argument("--peticion", default=PETICION)

    p_mod = sub.add_parser("modificar", help="Modificar cita: anula la actual y da de alta una nueva")
    p_mod.add_argument("--tipo", required=True, choices=["X","D"], help="X=NIE  D=DNI")
    p_mod.add_argument("--id",   required=True, help="Número de documento (ej. 12345678Z)")
    p_mod.add_argument("--peticion",   default=PETICION)
    p_mod.add_argument("--accion",     default="", help="idAccion (opcional)")
    p_mod.add_argument("--tramite",    default="", help="idTramite (opcional)")
    p_mod.add_argument("--comisaria",  default="", help="idComisaria (opcional)")
    p_mod.add_argument("--movil",      default="", help="idMovil (opcional)")

    p_sms = sub.add_parser("sms", help="Enviar un SMS")
    p_sms.add_argument("--to",      required=True, help="Número en formato E.164 (ej. +34612345678)")
    p_sms.add_argument("--mensaje", required=True, help="Texto del SMS")

    p_gen = sub.add_parser("crear-codigo", help="Generar un nuevo código de petición aleatorio")

    args = parser.parse_args()

    print("Conectando al MCP...")
    client = MCPClient()
    client.initialize()

    if args.cmd == "comisarias":
        print("Consultando comisarías...")
        resp = client.tool("consultar_comisarias", {
            "codigo_peticion": args.peticion,
            "id_provincia":    args.provincia,
            "id_localidad":    args.localidad,
        })

    elif args.cmd == "cita":
        print("Consultando cita...")
        resp = client.tool("consultar_cita_dnie", {
            "codigo_peticion": args.peticion,
            "tipo_titular":    args.tipo,
            "id_titular":      args.id,
        })

    elif args.cmd == "alta":
        print("Dando de alta cita...")
        resp = client.tool("alta_cita_dnie", {
            "codigo_peticion": args.peticion,
            "tipo_titular":    args.tipo,
            "id_titular":      args.id,
            "id_accion":       args.accion,
            "id_tramite":      args.tramite,
            "id_comisaria":    args.comisaria,
            "id_movil":        args.movil,
        })

    elif args.cmd == "anular":
        print("Anulando cita...")
        resp = client.tool("anular_cita_dnie", {
            "codigo_peticion": args.peticion,
            "tipo_titular":    args.tipo,
            "id_titular":      args.id,
        })

    elif args.cmd == "modificar":
        print("Modificando cita...")
        resp = client.tool("modificar_cita_dnie", {
            "codigo_peticion": args.peticion,
            "tipo_titular":    args.tipo,
            "id_titular":      args.id,
            "id_accion":       args.accion,
            "id_tramite":      args.tramite,
            "id_comisaria":    args.comisaria,
            "id_movil":        args.movil,
        })

    elif args.cmd == "sms":
        print("Enviando SMS...")
        resp = client.tool("enviar_sms", {
            "destinatario": args.to,
            "mensaje":      args.mensaje,
        })

    elif args.cmd == "crear-codigo":
        print("Generando código de petición...")
        resp = client.tool("crear_codigo_peticion", {})

    if not resp:
        print("Sin respuesta del servidor")
        return

    structured = resp.get("result", {}).get("structuredContent", {})

    if not structured.get("ok"):
        err = structured.get("error", {})
        render_error(err.get("code","?"), err.get("message","?"))
        return

    data = structured.get("data", {})

    if args.cmd == "comisarias":
        render_comisarias(data)
    elif args.cmd == "cita":
        render_cita(data)
    elif args.cmd in ("alta", "anular", "modificar", "sms", "crear-codigo"):
        render_resultado(data)


if __name__ == "__main__":
    main()