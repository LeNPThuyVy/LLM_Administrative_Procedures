import json
import re
from pathlib import Path
from typing import Any, Optional
import yaml

from domains import DOMAINS_DIR
from domains.domain_loader import DomainConfig


class AIChunkPlanner:
    """
    AI Chunk Planner: Sử dụng Qwen 3B (1-shot JSON mode) kết hợp Heuristic Fallback
    để phân tích mẫu dữ liệu và thông tin Domain của người dùng, từ đó lập kế hoạch
    ánh xạ cột (column mapping), thiết kế các chunk chuyên biệt và sinh entity_keywords.
    """

    def __init__(self, config: DomainConfig):
        self.config = config
        self.domain_id = config.domain_id

    def extract_data_profile(self, raw_docs: list) -> dict[str, Any]:
        """
        Trích xuất thông tin cấu trúc (profile) từ các RawDocument vừa được nạp.
        """
        if not raw_docs:
            return {"type": "empty", "columns": [], "samples": []}

        first_doc = raw_docs[0]
        metadata = getattr(first_doc, "metadata", {}) or {}

        if metadata and isinstance(metadata, dict) and len(metadata) > 0:
            columns = [str(k).strip() for k in metadata.keys()]
            samples = []
            for doc in raw_docs[:2]:
                doc_meta = getattr(doc, "metadata", {}) or {}
                sample_row = {}
                for col in columns:
                    val = str(doc_meta.get(col, "") or "").strip()
                    if len(val) > 120:
                        val = val[:120] + "..."
                    sample_row[col] = val
                samples.append(sample_row)

            return {
                "type": "tabular",
                "columns": columns,
                "samples": samples,
                "total_rows": len(raw_docs),
            }

        sample_text = getattr(first_doc, "raw_text", "") or ""
        return {
            "type": "document",
            "columns": [],
            "samples": [sample_text[:800]],
            "total_rows": len(raw_docs),
        }

    def plan_with_llm(self, profile: dict[str, Any]) -> Optional[dict[str, Any]]:
        """
        Gọi Qwen 3B (port 8080 hoặc 8081) với prompt 1-shot ở json_mode
        để thiết kế kế hoạch chunking theo nghiệp vụ của Domain.
        """
        if profile.get("type") != "tabular" or not profile.get("columns"):
            return None

        prompt = f"""Bạn là một chuyên gia kiến trúc dữ liệu AI RAG.
Hệ thống đang nạp dữ liệu mới cho một Lĩnh vực (Domain) với các thông tin sau:
- Tên Domain: "{self.config.domain_name or self.domain_id}"
- Mô tả: "{self.config.description}"
- Vai trò trợ lý: "{self.config.assistant_role}"

Dữ liệu nguồn gồm các cột sau:
{json.dumps(profile["columns"], ensure_ascii=False)}

Dữ liệu mẫu 2 dòng đầu:
{json.dumps(profile["samples"], ensure_ascii=False, indent=2)}

Nhiệm vụ của bạn: Hãy phân tích ngữ nghĩa các cột và trả về một JSON duy nhất có cấu trúc:
{{
  "id_column": "Tên cột mã định danh hoặc số thứ tự nếu có (chuỗi chính xác trong danh sách cột trên, hoặc null)",
  "title_column": "Tên cột làm tiêu đề chính của từng dòng (tên món ăn, tên địa điểm, tên quy trình...) - BẮT BUỘC chọn 1 cột",
  "category_column": "Tên cột thể hiện thể loại / phân loại nếu có (hoặc null)",
  "aliases_column": "Tên cột thể hiện tên gọi khác / từ khóa nếu có (hoặc null)",
  "chunk_specs": [
    {{
      "field_key": "Mã trường không dấu (vd: general, ingredients, steps, fee, time...)",
      "label": "Nhãn tiếng Việt (vd: Thông tin tổng quan, Nguyên liệu, Cách làm...)",
      "source_columns": ["Danh sách các cột thuộc trường này"]
    }}
  ],
  "entity_keywords": ["Danh sách 6-10 từ khóa cốt lõi đặc trưng của lĩnh vực này để hỗ trợ nhận diện câu hỏi của người dùng"]
}}

Quy tắc bắt buộc:
1. Mọi tên cột trong id_column, title_column, category_column, aliases_column và source_columns PHẢI nằm chính xác trong danh sách cột được cung cấp.
2. Luôn có 1 chunk tổng quát "general" gom toàn bộ thông tin quan trọng.
3. Chỉ trả về JSON hợp lệ, không giải thích gì thêm."""

        try:
            from rag.generator import _generate_via_server, _SERVER_PORT_3B, _SERVER_PORT_1_5B
            resp_text = _generate_via_server(prompt, port=_SERVER_PORT_3B, temperature=0.1, json_mode=True)
            if not resp_text:
                resp_text = _generate_via_server(prompt, port=_SERVER_PORT_1_5B, temperature=0.1, json_mode=True)

            if resp_text:
                cleaned = resp_text.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.startswith("```"):
                    cleaned = cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                parsed = json.loads(cleaned.strip())
                return parsed
        except Exception as e:
            print(f"[ai_chunk_planner] LLM planning note ({e}), falling back to heuristic")

        return None

    def fallback_heuristic_plan(self, profile: dict[str, Any]) -> dict[str, Any]:
        """
        Bộ quy tắc Heuristic thông minh dự phòng khi LLM không khả dụng.
        Tự động nhận diện cột tiêu đề, ID, phân loại và từ khóa.
        """
        cols = profile.get("columns", [])
        if not cols:
            return {
                "id_column": None,
                "title_column": None,
                "category_column": None,
                "aliases_column": None,
                "chunk_specs": [{"field_key": "general", "label": "Thông tin chi tiết", "source_columns": []}],
                "entity_keywords": [self.config.domain_name.lower().strip()] if self.config.domain_name else [],
            }

        col_lower_map = {c.strip().lower(): c for c in cols}

        # 1. Tìm ID
        id_col = None
        for cand in ["document_id", "id", "stt", "mã", "ma", "code"]:
            if cand in col_lower_map:
                id_col = col_lower_map[cand]
                break

        # 2. Tìm Title
        title_col = None
        for cand in [
            "title", "name", "tên", "ten", "tên món", "tên món ăn", "ten_mon",
            "ten_mon_an", "dish_name", "recipe_name", "procedure_name", "tên thủ tục",
            "tiêu đề", "tên địa điểm", "tên bài viết", "chủ đề"
        ]:
            if cand in col_lower_map:
                title_col = col_lower_map[cand]
                break

        if not title_col:
            # Chọn cột chuỗi đầu tiên không phải ID
            for c in cols:
                if c != id_col:
                    title_col = c
                    break
        if not title_col:
            title_col = cols[0]

        # 3. Tìm Category
        category_col = None
        for cand in ["category", "loại", "loại món", "danh mục", "nhóm", "group", "chuyên mục"]:
            if cand in col_lower_map:
                category_col = col_lower_map[cand]
                break

        # 4. Tìm Aliases
        aliases_col = None
        for cand in ["aliases", "từ khóa", "tu_khoa", "keywords", "tags"]:
            if cand in col_lower_map:
                aliases_col = col_lower_map[cand]
                break

        # 5. Phân nhóm cột cho chunk_specs
        chunk_specs = []
        special_groups = {
            "ingredients": {
                "label": "Nguyên liệu",
                "keywords": ["nguyên liệu", "nguyen_lieu", "gia vị", "thành phần", "ingredients"],
            },
            "steps": {
                "label": "Cách chế biến và thực hiện",
                "keywords": ["cách làm", "cach_lam", "chế biến", "hướng dẫn", "các bước", "thực hiện", "steps", "instructions"],
            },
            "fee": {
                "label": "Chi phí / Giá cả",
                "keywords": ["giá", "gia", "lệ phí", "chi phí", "fee", "price", "price_range"],
            },
            "time": {
                "label": "Thời gian",
                "keywords": ["thời gian", "thoi_gian", "thời hạn", "processing_time", "duration"],
            },
        }

        used_cols = set()
        for field_key, group_info in special_groups.items():
            matched_cols = []
            for c in cols:
                c_low = c.strip().lower()
                if any(kw in c_low for kw in group_info["keywords"]):
                    matched_cols.append(c)
                    used_cols.add(c)
            if matched_cols:
                chunk_specs.append({
                    "field_key": field_key,
                    "label": group_info["label"],
                    "source_columns": matched_cols,
                })

        # Luôn có chunk general gom tất cả các cột còn lại hoặc toàn bộ thông tin
        general_cols = [c for c in cols if c != id_col]
        chunk_specs.append({
            "field_key": "general",
            "label": "Thông tin tổng quan",
            "source_columns": general_cols,
        })

        # Gợi ý keywords
        domain_name = self.config.domain_name or self.domain_id
        entity_keywords = [domain_name.lower().strip()]
        if "nấu" in domain_name.lower() or "ăn" in domain_name.lower():
            entity_keywords.extend(["món ăn", "công thức", "nguyên liệu", "cách nấu", "chế biến", "gia vị"])

        return {
            "id_column": id_col,
            "title_column": title_col,
            "category_column": category_col,
            "aliases_column": aliases_col,
            "chunk_specs": chunk_specs,
            "entity_keywords": list(set(entity_keywords)),
        }

    def create_plan(self, raw_docs: list) -> dict[str, Any]:
        """
        Tạo và chuẩn hóa kế hoạch Chunking.
        Ưu tiên Qwen 3B, tự động đối soát với danh sách cột thực tế và fallback Heuristic.
        """
        profile = self.extract_data_profile(raw_docs)
        if profile.get("type") != "tabular":
            return {
                "column_mapping": {},
                "chunk_specs": [{"field_key": "general", "label": "Nội dung chi tiết", "source_columns": []}],
                "entity_keywords": [],
            }

        valid_cols = set(profile.get("columns", []))
        llm_plan = self.plan_with_llm(profile)
        heuristic_plan = self.fallback_heuristic_plan(profile)

        if not llm_plan:
            final_plan = heuristic_plan
        else:
            # Xác thực kế hoạch của LLM: chống bịa cột
            title_col = llm_plan.get("title_column")
            if not title_col or title_col not in valid_cols:
                title_col = heuristic_plan["title_column"]

            id_col = llm_plan.get("id_column")
            if id_col and id_col not in valid_cols:
                id_col = heuristic_plan["id_column"]

            cat_col = llm_plan.get("category_column")
            if cat_col and cat_col not in valid_cols:
                cat_col = heuristic_plan["category_column"]

            alias_col = llm_plan.get("aliases_column")
            if alias_col and alias_col not in valid_cols:
                alias_col = heuristic_plan["aliases_column"]

            raw_specs = llm_plan.get("chunk_specs") or []
            validated_specs = []
            has_general = False
            for spec in raw_specs:
                f_key = re.sub(r"[^a-z0-9_]", "_", str(spec.get("field_key", "")).lower().strip())
                if not f_key:
                    continue
                label = str(spec.get("label", f_key)).strip()
                s_cols = [c for c in spec.get("source_columns", []) if c in valid_cols]
                if s_cols:
                    if f_key == "general":
                        has_general = True
                    validated_specs.append({
                        "field_key": f_key,
                        "label": label,
                        "source_columns": s_cols,
                    })

            if not has_general:
                validated_specs.append({
                    "field_key": "general",
                    "label": "Thông tin tổng quan",
                    "source_columns": [c for c in valid_cols if c != id_col],
                })

            entity_keywords = llm_plan.get("entity_keywords") or heuristic_plan["entity_keywords"]
            if isinstance(entity_keywords, list):
                entity_keywords = [str(k).strip() for k in entity_keywords if str(k).strip()]
            else:
                entity_keywords = heuristic_plan["entity_keywords"]

            final_plan = {
                "id_column": id_col,
                "title_column": title_col,
                "category_column": cat_col,
                "aliases_column": alias_col,
                "chunk_specs": validated_specs or heuristic_plan["chunk_specs"],
                "entity_keywords": entity_keywords,
            }

        # Lưu cấu hình chunk_fields và entity_keywords mới vào config.yaml của domain
        self._sync_config(final_plan)

        return {
            "column_mapping": {
                "id_column": final_plan["id_column"],
                "title_column": final_plan["title_column"],
                "category_column": final_plan["category_column"],
                "aliases_column": final_plan["aliases_column"],
            },
            "chunk_specs": final_plan["chunk_specs"],
            "entity_keywords": final_plan["entity_keywords"],
        }

    def _sync_config(self, plan: dict[str, Any]) -> None:
        """
        Cập nhật chunk_fields, chunk_field_specs và bổ sung entity_keywords vào config.yaml
        """
        config_path = DOMAINS_DIR / self.domain_id / "config.yaml"
        if not config_path.exists():
            return

        try:
            current_cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            chunk_fields = []
            chunk_field_specs = {}

            for spec in plan.get("chunk_specs", []):
                f_key = spec["field_key"]
                suffix = f"_{f_key}" if not f_key.startswith("_") else f_key
                chunk_fields.append(f_key)
                chunk_field_specs[f_key] = {
                    "suffix": suffix,
                    "label": spec["label"],
                    "attr": f_key,
                    "source_columns": spec.get("source_columns", []),
                }

            current_cfg["chunk_fields"] = chunk_fields
            current_cfg["chunk_field_specs"] = chunk_field_specs

            existing_kws = current_cfg.get("entity_keywords", [])
            new_kws = plan.get("entity_keywords", [])
            combined_kws = list(dict.fromkeys(existing_kws + new_kws))
            current_cfg["entity_keywords"] = combined_kws

            with open(config_path, "w", encoding="utf-8") as fp:
                yaml.dump(current_cfg, fp, allow_unicode=True, sort_keys=False)

            # Cập nhật trực tiếp trên self.config
            self.config.chunk_fields = chunk_fields
            self.config.chunk_field_specs = chunk_field_specs
            self.config.entity_keywords = combined_kws
            print(f"[ai_chunk_planner][{self.domain_id}] Synced config: {len(chunk_fields)} chunk fields, {len(combined_kws)} entity keywords")
        except Exception as e:
            print(f"[ai_chunk_planner][{self.domain_id}] Warning syncing config.yaml: {e}")
