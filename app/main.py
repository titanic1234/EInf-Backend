# main.py
# Grundkonstrukt des Servers mit KI erstellt. FastAPI war eigene Vorgabe



from fastapi import FastAPI, WebSocket
from app.routers.games import router as games_router
from app.ws_routing.handler import handle_websocket

app = FastAPI(title="Schiffe Versenken Backend")

app.include_router(games_router)


@app.get("/")
def root():
    return {"message": "Schiffe Versenken Backend is running"}


@app.websocket("/ws/{code}")
async def websocket_endpoint(websocket: WebSocket, code: str):
    token = websocket.query_params.get("token")
    await handle_websocket(websocket, code, token)