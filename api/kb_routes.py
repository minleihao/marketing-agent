from __future__ import annotations

from flask import Blueprint, jsonify, request

from storage.kb_store import create_kb, get_kb, list_kb, update_kb


kb_routes = Blueprint("kb_routes", __name__, url_prefix="/api/kb")


@kb_routes.post("")
def create_kb_route():
    data = request.get_json(force=True, silent=True) or {}
    try:
        kb = create_kb(data)
        return jsonify(kb.model_dump()), 201
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@kb_routes.get("/list")
def list_kb_route():
    items = [kb.model_dump() for kb in list_kb()]
    return jsonify(items)


@kb_routes.get("/<kb_id>")
def get_kb_route(kb_id: str):
    kb = get_kb(kb_id)
    if not kb:
        return jsonify({"error": "KB not found"}), 404
    return jsonify(kb.model_dump())


@kb_routes.put("/<kb_id>")
def update_kb_route(kb_id: str):
    data = request.get_json(force=True, silent=True) or {}
    try:
        kb = update_kb(kb_id, data)
        return jsonify(kb.model_dump())
    except FileNotFoundError:
        return jsonify({"error": "KB not found"}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
