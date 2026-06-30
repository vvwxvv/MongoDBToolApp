# flask_app.py
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from src.mongo_lib import MongoConnectionManager, close_connection
from src.mongo_lib.config import get_settings
from src.mongo_lib.repository import BaseRepository
from src.mongo_lib import MongoBaseModel, DocumentNotFoundException, DuplicateKeyException, InvalidObjectIdError
import logging
import atexit
import functools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ------------------------------------------------------------------
# Repository factory (dynamic model)
# ------------------------------------------------------------------
def get_repo(collection_name, db_name=None):
    class DynamicDocument(MongoBaseModel):
        model_config = {"extra": "allow"}
    return BaseRepository[DynamicDocument](
        collection_name=collection_name,
        model=DynamicDocument,
        db_name=db_name,
    )

# ------------------------------------------------------------------
# Graceful shutdown – close MongoDB connection when app exits
# ------------------------------------------------------------------
def shutdown():
    logger.info("Shutting down MongoDB connection...")
    close_connection()  # use the module-level function

atexit.register(shutdown)

# ------------------------------------------------------------------
# Decorator for error handling (preserves original function name)
# ------------------------------------------------------------------
def handle_crud_errors(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except InvalidObjectIdError as e:
            return jsonify({"error": str(e)}), 400
        except DocumentNotFoundException as e:
            return jsonify({"error": str(e)}), 404
        except DuplicateKeyException as e:
            return jsonify({"error": str(e)}), 409
        except Exception as e:
            logger.exception("Unexpected error")
            return jsonify({"error": "Internal server error"}), 500
    return wrapper

# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------
@app.route('/')
def home():
    db_name = get_settings().db_name
    return render_template('index.html', db_name=db_name)

@app.route('/health')
def health():
    try:
        mgr = MongoConnectionManager.get_instance()
        ok = mgr.health_check()
        if not ok:
            return jsonify({"status": "unhealthy", "database": get_settings().db_name}), 503
        return jsonify({"status": "ok", "database": get_settings().db_name})
    except Exception as e:
        logger.error("Health check failed: %s", str(e))
        return jsonify({"status": "error", "detail": str(e)}), 503

# ------------------------------------------------------------------
# Writing endpoints
# ------------------------------------------------------------------
@app.route('/writing', methods=['GET'])
@handle_crud_errors
def list_writing():
    repo = get_repo('Writing', 'WXNoteBookApp')
    skip = int(request.args.get('skip', 0))
    limit = int(request.args.get('limit', 50))
    docs = repo.find(skip=skip, limit=limit)
    return jsonify([doc.model_dump(by_alias=True) for doc in docs])

@app.route('/writing', methods=['POST'])
@handle_crud_errors
def create_writing():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400
    repo = get_repo('Writing', 'WXNoteBookApp')
    class DynamicDocument(MongoBaseModel):
        model_config = {"extra": "allow"}
    doc = DynamicDocument(**data)
    inserted_id = repo.create(doc)
    return jsonify({"id": str(inserted_id)}), 201

@app.route('/writing/<item_id>', methods=['GET'])
@handle_crud_errors
def get_writing(item_id):
    repo = get_repo('Writing', 'WXNoteBookApp')
    doc = repo.require_by_id(item_id)
    return jsonify(doc.model_dump(by_alias=True))

@app.route('/writing/<item_id>', methods=['PATCH'])
@handle_crud_errors
def update_writing(item_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400
    repo = get_repo('Writing', 'WXNoteBookApp')
    updated = repo.update(item_id, data)
    if updated is None:
        return jsonify({"error": "Document not found"}), 404
    return jsonify(updated.model_dump(by_alias=True))

@app.route('/writing/<item_id>', methods=['DELETE'])
@handle_crud_errors
def delete_writing(item_id):
    repo = get_repo('Writing', 'WXNoteBookApp')
    deleted = repo.delete(item_id)
    if not deleted:
        return jsonify({"error": "Document not found"}), 404
    return '', 204

# ------------------------------------------------------------------
# Artwork endpoints
# ------------------------------------------------------------------
@app.route('/artwork', methods=['GET'])
@handle_crud_errors
def list_artwork():
    repo = get_repo('Artwork', 'TestMy')
    skip = int(request.args.get('skip', 0))
    limit = int(request.args.get('limit', 50))
    docs = repo.find(skip=skip, limit=limit)
    return jsonify([doc.model_dump(by_alias=True) for doc in docs])

@app.route('/artwork', methods=['POST'])
@handle_crud_errors
def create_artwork():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400
    repo = get_repo('Artwork', 'TestMy')
    class DynamicDocument(MongoBaseModel):
        model_config = {"extra": "allow"}
    doc = DynamicDocument(**data)
    inserted_id = repo.create(doc)
    return jsonify({"id": str(inserted_id)}), 201

@app.route('/artwork/<item_id>', methods=['GET'])
@handle_crud_errors
def get_artwork(item_id):
    repo = get_repo('Artwork', 'TestMy')
    doc = repo.require_by_id(item_id)
    return jsonify(doc.model_dump(by_alias=True))

@app.route('/artwork/<item_id>', methods=['PATCH'])
@handle_crud_errors
def update_artwork(item_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400
    repo = get_repo('Artwork', 'TestMy')
    updated = repo.update(item_id, data)
    if updated is None:
        return jsonify({"error": "Document not found"}), 404
    return jsonify(updated.model_dump(by_alias=True))

@app.route('/artwork/<item_id>', methods=['DELETE'])
@handle_crud_errors
def delete_artwork(item_id):
    repo = get_repo('Artwork', 'TestMy')
    deleted = repo.delete(item_id)
    if not deleted:
        return jsonify({"error": "Document not found"}), 404
    return '', 204

# ------------------------------------------------------------------
# Favicon
# ------------------------------------------------------------------
@app.route('/favicon.ico')
def favicon():
    return '', 204

# ------------------------------------------------------------------
# Run locally (debug=False to avoid Windows socket issues)
# ------------------------------------------------------------------
if __name__ == '__main__':
    # Set debug=False for production; if you need debugging, set to True
    # but be aware of the OSError on Windows with reloader.
    app.run(host='127.0.0.1', port=8000, debug=False)