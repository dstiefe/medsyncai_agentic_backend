"""
MedSync AI v2 - Device Search & Database Loading

Handles:
- Firebase device database loading
- Whoosh in-memory search index
- Device search helper for name resolution
- Field filtering utilities

Ported from vs2/agents/get_databases.py, vs2/agents/search.py, vs2/utils/device_search.py
"""

import os
import json
import difflib
import firebase_admin
from firebase_admin import credentials, firestore
from typing import Optional, Dict, List, Union
import asyncio
from datetime import datetime
from google.cloud.firestore_v1 import Increment

from whoosh.fields import Schema, TEXT, ID
from whoosh.filedb.filestore import RamStorage
from whoosh.analysis import RegexTokenizer, LowercaseFilter
from whoosh.query import Or, And, Term, Phrase, FuzzyTerm

from medsync_ai_v2 import config


# =============================================================================
# FirebaseDB - Firestore abstraction layer
# =============================================================================

class FirebaseDB:
    def __init__(self, cred_path: str, collection_name: str):
        self.cred_path = cred_path
        self.collection_name = collection_name

        if not firebase_admin._apps:
            cred = credentials.Certificate(self.cred_path)
            firebase_admin.initialize_app(cred)

        self.db = firestore.client()
        self.collection_ref = self.db.collection(self.collection_name)

    def get_all_documents(self) -> List[Dict]:
        docs = self.collection_ref.stream()
        records = []
        for doc in docs:
            record = doc.to_dict()
            record["uid"] = doc.id
            records.append(record)
        return records

    async def get_document_async(self, doc_id: str) -> Optional[Dict]:
        def _get():
            doc = self.collection_ref.document(doc_id).get()
            return doc.to_dict() if doc.exists else None
        return await asyncio.to_thread(_get)

    async def add_document_async(self, data: dict, doc_id: Optional[str] = None):
        def _write():
            if doc_id:
                self.collection_ref.document(doc_id).set(data)
            else:
                doc_ref = self.collection_ref.document()
                data['id'] = doc_ref.id
                doc_ref.set(data)
            return data
        return await asyncio.to_thread(_write)

    async def update_document_async(self, doc_id: str, updates: dict):
        def _write():
            self.collection_ref.document(doc_id).update(updates)
        await asyncio.to_thread(_write)

    async def get_subcollection_doc_async(self, parent_id, subcollection_name, doc_id):
        def _get():
            doc_ref = self.db.collection(self.collection_name).document(parent_id).collection(subcollection_name).document(doc_id)
            doc = doc_ref.get()
            return doc.to_dict() if doc.exists else None
        return await asyncio.to_thread(_get)

    async def save_to_subcollection_async(self, parent_id, subcollection_name, doc_id, data):
        def _write():
            doc_ref = self.db.collection(self.collection_name).document(parent_id).collection(subcollection_name).document(doc_id)
            doc_ref.set(data)
        await asyncio.to_thread(_write)

    async def add_subcollection_document_async(self, parent_doc_id, subcollection_name, data, doc_id=None):
        def _write():
            sub_ref = self.collection_ref.document(parent_doc_id).collection(subcollection_name)
            if doc_id:
                doc_ref = sub_ref.document(doc_id)
                data["id"] = doc_id
                doc_ref.set(data)
            else:
                doc_ref = sub_ref.document()
                data["id"] = doc_ref.id
                doc_ref.set(data)
            return data
        return await asyncio.to_thread(_write)

    async def add_nested_document_async(self, path_segments: list, data: dict, doc_id: str = None):
        def _write():
            ref = self.collection_ref
            for i, segment in enumerate(path_segments):
                if i % 2 == 0:
                    ref = ref.document(segment)
                else:
                    ref = ref.collection(segment)
            if doc_id:
                doc_ref = ref.document(doc_id)
                data["id"] = doc_id
                doc_ref.set(data)
            else:
                doc_ref = ref.document()
                data["id"] = doc_ref.id
                doc_ref.set(data)
            return data
        return await asyncio.to_thread(_write)

    async def save_to_nested_subcollection_async(self, parent_id, subcollection_path, doc_id, data):
        def _write():
            path = f"{self.collection_name}/{parent_id}/{subcollection_path}/{doc_id}"
            segments = path.split("/")
            ref = self.db.collection(segments[0])
            segments = segments[1:]
            while segments:
                part = segments.pop(0)
                if segments:
                    ref = ref.document(part)
                    ref = ref.collection(segments.pop(0))
                else:
                    ref = ref.document(part)
            ref.set(data)
        await asyncio.to_thread(_write)

    async def update_user_tokens_async(self, doc_id, input_tokens, output_tokens, last_updated):
        updates = {
            "input_tokens": Increment(input_tokens),
            "output_tokens": Increment(output_tokens),
            "last_updated": last_updated,
        }
        await self.update_document_async(doc_id, updates)

    async def get_documents_by_field_in_async(self, field_name, field_values):
        if not field_values:
            return []

        def _query():
            all_records = []
            seen_ids = set()
            batch_size = 10
            for i in range(0, len(field_values), batch_size):
                batch = field_values[i:i + batch_size]
                query = self.collection_ref.where(field_name, "in", batch)
                docs = query.stream()
                for doc in docs:
                    if doc.id not in seen_ids:
                        record = doc.to_dict()
                        record["uid"] = doc.id
                        all_records.append(record)
                        seen_ids.add(doc.id)
            return all_records

        return await asyncio.to_thread(_query)


# =============================================================================
# Device Database Loading
# =============================================================================

# Module-level caches
_DATABASE = None
_TEXT_SEARCH = None
_WHOOSH_INDEX = None


def load_text_search() -> list:
    firebase_db = FirebaseDB(
        cred_path=config.FIREBASE_CRED_PATH,
        collection_name=config.FIREBASE_COLLECTION,
    )
    return firebase_db.get_all_documents()


def load_device_database() -> dict:
    firebase_db = FirebaseDB(
        cred_path=config.FIREBASE_CRED_PATH,
        collection_name=config.FIREBASE_COLLECTION,
    )
    docs = firebase_db.get_all_documents()
    holder = {}
    for doc in docs:
        holder[str(doc['id'])] = doc
    return holder


def get_database() -> dict:
    global _DATABASE
    if _DATABASE is None:
        print("Loading device database from Firebase...")
        _DATABASE = load_device_database()
        print(f"Loaded {len(_DATABASE)} devices.")
    return _DATABASE


def get_text_search() -> list:
    global _TEXT_SEARCH
    if _TEXT_SEARCH is None:
        print("Loading text search data from Firebase...")
        _TEXT_SEARCH = load_text_search()
        print(f"Loaded {len(_TEXT_SEARCH)} search records.")
    return _TEXT_SEARCH


# =============================================================================
# Whoosh Search Index
# =============================================================================

my_analyzer = RegexTokenizer() | LowercaseFilter()

schema = Schema(
    id=ID(stored=True, unique=True),
    device_name=TEXT(stored=True, analyzer=my_analyzer),
    manufacturer=TEXT(stored=True, analyzer=my_analyzer),
    product_name=TEXT(stored=True, analyzer=my_analyzer),
    aliases=TEXT(stored=True, analyzer=my_analyzer),
)


def build_whoosh_index():
    global _WHOOSH_INDEX
    text_search = get_text_search()

    storage = RamStorage()
    ix = storage.create_index(schema)
    writer = ix.writer()

    for doc in text_search:
        writer.add_document(
            id=str(int(doc['id'])),
            manufacturer=doc.get('manufacturer', ''),
            product_name=doc.get('product_name', ''),
            aliases=doc.get('aliases', ''),
            device_name=doc.get('device_name', ''),
        )

    writer.commit()
    _WHOOSH_INDEX = ix
    print(f"Built Whoosh index with {len(text_search)} documents.")
    return ix


def get_whoosh_index():
    global _WHOOSH_INDEX
    if _WHOOSH_INDEX is None:
        build_whoosh_index()
    return _WHOOSH_INDEX


# =============================================================================
# Device Search Helper
# =============================================================================

class DeviceSearchHelper:
    """Search for devices by name using Whoosh and package results."""

    async def search_devices(self, device_names: list) -> dict:
        ix = get_whoosh_index()
        analyzer = RegexTokenizer() | LowercaseFilter()
        found = {}
        not_found = []

        for device_name in device_names:
            device_name = device_name.strip()
            if not device_name:
                continue

            tokens = [token.text.lower() for token in analyzer(device_name)]
            if not tokens:
                not_found.append(device_name)
                continue

            query = Or([
                Phrase("product_name", tokens),
                Phrase("aliases", tokens),
                And([Term("product_name", t) for t in tokens]),
                And([Term("aliases", t) for t in tokens]),
            ])

            try:
                with ix.searcher() as searcher:
                    results = searcher.search(query, limit=100)
                    if results:
                        ids = [hit.get("id") for hit in results]
                        found[device_name] = ids
                    else:
                        not_found.append(device_name)
            except Exception as e:
                print(f"Search error for '{device_name}': {e}")
                not_found.append(device_name)

        return {"found": found, "not_found": not_found}

    def suggest_close_matches(self, device_name: str, max_suggestions: int = 5) -> list:
        """
        Find close matches for an unresolved device name.

        Uses Whoosh FuzzyTerm (edit distance) then difflib fallback against
        all product_name values in DATABASE.

        Returns list of dicts sorted by score descending:
            [{"product_name": str, "device_name": str, "score": float}, ...]
        """
        suggestions = {}  # product_name -> {product_name, device_name, score}

        # ── Tier 1: Whoosh FuzzyTerm ──────────────────────────
        ix = get_whoosh_index()
        analyzer = RegexTokenizer() | LowercaseFilter()
        tokens = [t.text for t in analyzer(device_name)]

        if tokens:
            fuzzy_queries = []
            for token in tokens:
                for field in ("product_name", "device_name", "aliases"):
                    fuzzy_queries.append(FuzzyTerm(field, token, maxdist=2, prefixlength=1))

            query = Or(fuzzy_queries)
            try:
                with ix.searcher() as searcher:
                    results = searcher.search(query, limit=20)
                    for hit in results:
                        pname = hit.get("product_name", "")
                        dname = hit.get("device_name", "")
                        if pname and pname not in suggestions:
                            suggestions[pname] = {
                                "product_name": pname,
                                "device_name": dname,
                                "score": round(min(hit.score / 10.0, 1.0), 2),
                            }
            except Exception as e:
                print(f"  [DeviceSearch] FuzzyTerm error for '{device_name}': {e}")

        # ── Tier 2: difflib fallback ──────────────────────────
        database = get_database()
        all_product_names = list({
            v.get("product_name", "")
            for v in database.values()
            if v.get("product_name")
        })

        lower_to_original = {}
        for name in all_product_names:
            lower_to_original.setdefault(name.lower(), name)

        close = difflib.get_close_matches(
            device_name.lower(),
            [n.lower() for n in all_product_names],
            n=max_suggestions,
            cutoff=0.5,
        )

        for match_lower in close:
            original = lower_to_original.get(match_lower, match_lower)
            if original not in suggestions:
                dev_name = ""
                for v in database.values():
                    if v.get("product_name") == original:
                        dev_name = v.get("device_name", "")
                        break
                ratio = difflib.SequenceMatcher(
                    None, device_name.lower(), match_lower
                ).ratio()
                suggestions[original] = {
                    "product_name": original,
                    "device_name": dev_name,
                    "score": round(ratio, 2),
                }

        # Sort by score descending, limit
        result = sorted(suggestions.values(), key=lambda x: x["score"], reverse=True)
        return result[:max_suggestions]

    def extract_device_specs(self, device_id: str):
        """
        Extract specifications for a single device from DATABASE.

        Returns dict with device info and specifications, or None if not found.
        """
        database = get_database()
        device = database.get(str(device_id), database.get(device_id, {}))

        if not device:
            return None

        spec_fields = [
            ("specification_inner-diameter_in", "ID_in"),
            ("specification_inner-diameter_mm", "ID_mm"),
            ("specification_inner-diameter_F", "ID_Fr"),
            ("specification_outer-diameter-distal_in", "OD_distal_in"),
            ("specification_outer-diameter-distal_mm", "OD_distal_mm"),
            ("specification_outer-diameter-distal_F", "OD_distal_Fr"),
            ("specification_outer-diameter-proximal_in", "OD_proximal_in"),
            ("specification_outer-diameter-proximal_mm", "OD_proximal_mm"),
            ("specification_outer-diameter-proximal_F", "OD_proximal_Fr"),
            ("specification_length_cm", "length_cm"),
        ]

        compat_fields = [
            ("compatibility_wire_max_outer-diameter_in", "wire_max_OD_in"),
            ("compatibility_wire_max_outer-diameter_mm", "wire_max_OD_mm"),
            ("compatibility_catheter_max_outer-diameter_in", "catheter_max_OD_in"),
            ("compatibility_catheter_max_outer-diameter_mm", "catheter_max_OD_mm"),
            ("compatibility_catheter_req_inner-diameter_in", "catheter_required_ID_in"),
            ("compatibility_catheter_req_inner-diameter_mm", "catheter_required_ID_mm"),
            ("compatibility_guide_or_catheter_or_sheath_min_inner-diameter_in", "guide_min_ID_in"),
            ("compatibility_guide_or_catheter_or_sheath_min_inner-diameter_mm", "guide_min_ID_mm"),
        ]

        result = {
            "device_id": device_id,
            "product_name": device.get("product_name", "Unknown"),
            "device_name": device.get("device_name", "Unknown"),
            "manufacturer": device.get("manufacturer", "Unknown"),
            "conical_category": device.get("conical_category", "Unknown"),
            "logic_category": device.get("logic_category", "Unknown"),
        }

        specs = {}
        for db_field, label in spec_fields:
            value = device.get(db_field)
            if value is not None and value != "":
                specs[label] = value
        result["specifications"] = specs

        compat_specs = {}
        for db_field, label in compat_fields:
            value = device.get(db_field)
            if value is not None and value != "":
                compat_specs[label] = value
        result["compatibility"] = compat_specs

        return result

    def package_devices(self, found_devices: dict) -> dict:
        database = get_database()
        packaged = {"devices": {}}

        for device_name, ids in found_devices.items():
            if not ids:
                continue

            product_groups = {}
            for dev_id in ids:
                device = database.get(str(dev_id), database.get(dev_id, {}))
                if device:
                    pname = device.get("product_name", device_name)
                    cat = device.get("conical_category", "Unknown")
                    if pname not in product_groups:
                        product_groups[pname] = {"ids": [], "conical_category": cat}
                    product_groups[pname]["ids"].append(dev_id)

            packaged["devices"].update(product_groups)

        return packaged


# =============================================================================
# Field Filtering Utilities
# =============================================================================

key_fields = {
    "device_variant_id": "main",
    "manufacturer": "main",
    "device_variant": "main",
    "category_type": "main",
    "product_name": "main",
    "aliases": "main",
    "logic_category": "main",
    "conical_category": "main",
    "fit_logic": "main",
    "device_name": "main",
    "id": "main",
}


def filter_device_records(source_list: list, key_fields_map: dict, filter_list_type: list) -> list:
    filtered_records = []
    for record in source_list:
        filtered_record = {}
        for key, value in record.items():
            category = key_fields_map.get(key, "ignore")
            if category in filter_list_type:
                if isinstance(value, str):
                    if len(value) > 0:
                        filtered_record[key] = value
                else:
                    filtered_record[key] = value
        if "uid" in record:
            filtered_record["uid"] = record["uid"]
        filtered_records.append(filtered_record)
    return filtered_records
