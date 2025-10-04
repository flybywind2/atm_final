"""WebSocket connection management"""
from fastapi import WebSocket, WebSocketDisconnect


# Global WebSocket connections registry
active_connections: dict[str, WebSocket] = {}


async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time progress updates

    Args:
        websocket: WebSocket connection
        job_id: Job ID for tracking
    """
    await websocket.accept()
    active_connections[job_id] = websocket

    try:
        while True:
            # Receive messages from client (keep-alive)
            data = await websocket.receive_text()
            # Echo back (keep connection alive)
            await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        print(f"WebSocket 연결 종료: {job_id}")
        del active_connections[job_id]
    except Exception as e:
        print(f"WebSocket 에러: {e}")
        if job_id in active_connections:
            del active_connections[job_id]


def get_active_connections():
    """Get active WebSocket connections registry"""
    return active_connections
