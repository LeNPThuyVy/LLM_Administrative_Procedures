import json
import re
from pathlib import Path
from typing import Any, Optional
import yaml

from domains import DOMAINS_DIR
from domains.domain_loader import DomainConfig


class AIChunkPlanner:
    """
    AI Chunk Planner & Domain Prompt Generator:
    Sử dụng Qwen 3B (1-shot JSON mode) kết hợp Heuristic Fallback để:
    1. Phân tích ngữ cảnh dữ liệu từ 2 nhánh:
       - Nhánh Tabular (Excel, CSV, Structured JSON): Trích xuất schema cột và dòng mẫu {cột}: {nội dung dòng}.
       - Nhánh Document (PDF, DOCX): Trích xuất đề mục và đoạn văn bản mẫu.
    2. Tự động sinh cấu hình và prompt cho hệ thống:
       - Cập nhật Mô tả Domain và Vai trò trợ lý (nếu người dùng chưa điền hoặc điền sơ sài).
       - Tự thiết kế `system_prompt_rules` (3-5 quy tắc nghiệp vụ đặc thù của domain).
       - Tự thiết kế `answer_template` (Mẫu định dạng câu trả lời chuẩn theo dữ liệu).
       - Tự sinh `entity_keywords` và `clarification_prompt`.
       - Xác định `column_mapping` cho dữ liệu bảng.
    3. Đồng bộ cấu hình vào `domains/<domain_id>/config.yaml`.
    """

    def __init__(self, config: DomainConfig):
        self.config = config
        self.domain_id = config.domain_id

    def extract_data_profile(self, raw_docs: list) -> dict[str, Any]:
        """
        Trích xuất thông tin cấu trúc (profile) từ các RawDocument vừa được nạp.
        Nhận diện rõ nguồn tabular hay document.
        """
        if not raw_docs:
            return {"type": "empty", "columns": [], "samples": []}

        first_doc = raw_docs[0]
        metadata = getattr(first_doc, "metadata", {}) or {}
        source_type = metadata.get("_source_type", "") or metadata.get("source_type", "")

        # Kiểm tra nếu là dạng bảng (tabular metadata)
        non_system_keys = [k for k in metadata.keys() if not k.startswith("_") and k not in ("source_type", "document_id")]

        if source_type == "tabular" or (len(non_system_keys) > 1 and metadata):
            columns = [str(k).strip() for k in non_system_keys]
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

        # Dạng tài liệu phi cấu trúc (PDF, DOCX, text)
        sample_texts = []
        for doc in raw_docs[:3]:
            txt = (getattr(doc, "raw_text", "") or "").strip()
            if txt:
                sample_texts.append(txt[:500])

        return {
            "type": "document",
            "columns": [],
            "samples": sample_texts if sample_texts else [""],
            "total_rows": len(raw_docs),
        }

    def plan_with_llm(self, profile: dict[str, Any]) -> Optional[dict[str, Any]]:
        """
        Gọi Qwen 3B với prompt 1-shot ở json_mode để phân tích Domain và tự viết System Prompt.
        """
        p_type = profile.get("type", "document")
        domain_name = self.config.domain_name or self.domain_id
        desc = self.config.description or ""
        role = self.config.assistant_role or ""

        if p_type == "tabular":
            data_context = f"""Dữ liệu nguồn thuộc dạng BẢNG (Excel/CSV/JSON) với các cột sau:
{json.dumps(profile.get("columns", []), ensure_ascii=False)}

Dữ liệu mẫu 2 dòng đầu:
{json.dumps(profile.get("samples", []), ensure_ascii=False, indent=2)}"""
        else:
            data_context = f"""Dữ liệu nguồn thuộc dạng TÀI LIỆU VĂN BẢN (PDF/DOCX) với nội dung mẫu các đoạn đầu:
{json.dumps(profile.get("samples", []), ensure_ascii=False, indent=2)}"""

        prompt = f"""Bạn là một chuyên gia kiến trúc dữ liệu AI RAG cao cấp.
Hệ thống đang nạp dữ liệu cho một Lĩnh vực (Domain) mới:
- Mã Domain: "{self.domain_id}"
- Tên Domain: "{domain_name}"
- Mô tả hiện tại: "{desc}"
- Vai trò trợ lý hiện tại: "{role}"

{data_context}

Nhiệm vụ của bạn: Hãy phân tích sâu nội dung và ngữ nghĩa của dữ liệu trên để thiết lập hệ thống tư vấn AI hoàn chỉnh.
Trả về một JSON duy nhất có cấu trúc:
{{
  "domain_name": "Tên tiếng Việt chuẩn, rõ nghĩa của Lĩnh vực (nếu tên hiện tại sơ sài, hãy đặt tên chuyên nghiệp)",
  "description": "Mô tả chi tiết 1-2 câu về phạm vi thông tin mà trợ lý này sẽ hỗ trợ người dùng",
  "assistant_role": "Vai trò cụ thể của trợ lý (vd: chuyên gia tư vấn ẩm thực, cố vấn thủ tục, hướng dẫn viên du lịch...)",
  "id_column": "Tên cột mã ID hoặc STT nếu có trong danh sách cột (nếu không có thì null)",
  "title_column": "Tên cột làm tiêu đề chính của từng dòng (nếu là tài liệu văn bản thì null)",
  "category_column": "Tên cột phân loại nếu có (hoặc null)",
  "aliases_column": "Tên cột từ khóa/tên gọi khác nếu có (hoặc null)",
  "entity_keywords": ["Danh sách 6-10 từ khóa cốt lõi đặc trưng của lĩnh vực này để nhận diện câu hỏi"],
  "clarification_prompt": "Câu hỏi làm rõ thân thiện khi người dùng chỉ chào hỏi hoặc hỏi quá mơ hồ",
  "system_prompt_rules": "3-5 quy tắc nghiệp vụ cốt lõi khi trả lời câu hỏi trong lĩnh vực này (mỗi quy tắc bắt đầu bằng gạch đầu dòng, viết súc tích, yêu cầu bám sát bằng chứng)",
  "answer_template": "Mẫu định dạng khung câu trả lời mẫu (dùng bullet hoặc định dạng trực quan) để hướng dẫn AI trình bày thông tin mạch lạc theo đặc thù của dữ liệu này"
}}

Quy tắc bắt buộc:
1. Nếu là dạng bảng, id_column và title_column PHẢI nằm chính xác trong danh sách cột được cung cấp.
2. Trả về JSON hợp lệ, không kèm văn bản giải thích ngoài JSON."""

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
        Quy tắc Heuristic dự phòng khi LLM không phản hồi.
        """
        cols = profile.get("columns", [])
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

        if not title_col and cols:
            for c in cols:
                if c != id_col:
                    title_col = c
                    break
        if not title_col and cols:
            title_col = cols[0]

        # 3. Tìm Category & Aliases
        category_col = None
        for cand in ["category", "loại", "loại món", "danh mục", "nhóm", "group", "chuyên mục"]:
            if cand in col_lower_map:
                category_col = col_lower_map[cand]
                break

        aliases_col = None
        for cand in ["aliases", "từ khóa", "tu_khoa", "keywords", "tags"]:
            if cand in col_lower_map:
                aliases_col = col_lower_map[cand]
                break

        d_name = self.config.domain_name or self.domain_id
        entity_keywords = [d_name.lower().strip()]
        if cols:
            entity_keywords.extend([c.lower().strip() for c in cols[:5]])

        # Mẫu prompt rules
        rules = (
            f"- Cung cấp thông tin chính xác về {d_name} dựa trên bằng chứng được cung cấp.\n"
            "- Trình bày mạch lạc, rõ ràng các thông số và chi tiết quan trọng.\n"
            "- Nếu thông tin không có trong tài liệu, thông báo rõ ràng cho người dùng, không tự suy đoán."
        )

        template = (
            f"**Thông tin về:** [Tên mục / Chủ đề]\n"
            "- Chi tiết: [Nội dung cụ thể]\n"
            "- Ghi chú bổ sung: [Nếu có]"
        )

        clarification = f"Chào bạn, bạn muốn tìm hiểu thông tin gì về {d_name}? Vui lòng cung cấp thêm chi tiết để tôi có thể hỗ trợ bạn tốt nhất."

        return {
            "domain_name": d_name,
            "description": self.config.description or f"Hệ thống tra cứu và tư vấn thông tin về {d_name}.",
            "assistant_role": self.config.assistant_role or f"chuyên gia tư vấn {d_name}",
            "id_column": id_col,
            "title_column": title_col,
            "category_column": category_col,
            "aliases_column": aliases_col,
            "entity_keywords": list(dict.fromkeys(entity_keywords)),
            "clarification_prompt": clarification,
            "system_prompt_rules": rules,
            "answer_template": template,
        }

    def create_plan(self, raw_docs: list) -> dict[str, Any]:
        """
        Tạo kế hoạch cấu hình và prompt hoàn chỉnh cho domain.
        """
        profile = self.extract_data_profile(raw_docs)
        heuristic = self.fallback_heuristic_plan(profile)
        llm_plan = self.plan_with_llm(profile)

        if not llm_plan:
            final_plan = heuristic
        else:
            # Đối soát an toàn tránh bịa cột
            valid_cols = set(profile.get("columns", []))
            title_col = llm_plan.get("title_column")
            if profile.get("type") == "tabular" and (not title_col or title_col not in valid_cols):
                title_col = heuristic["title_column"]

            id_col = llm_plan.get("id_column")
            if id_col and id_col not in valid_cols:
                id_col = heuristic["id_column"]

            cat_col = llm_plan.get("category_column")
            if cat_col and cat_col not in valid_cols:
                cat_col = heuristic["category_column"]

            alias_col = llm_plan.get("aliases_column")
            if alias_col and alias_col not in valid_cols:
                alias_col = heuristic["aliases_column"]

            kws = llm_plan.get("entity_keywords") or heuristic["entity_keywords"]
            if isinstance(kws, list):
                entity_keywords = [str(k).strip() for k in kws if str(k).strip()]
            else:
                entity_keywords = heuristic["entity_keywords"]

            final_plan = {
                "domain_name": llm_plan.get("domain_name") or heuristic["domain_name"],
                "description": llm_plan.get("description") or heuristic["description"],
                "assistant_role": llm_plan.get("assistant_role") or heuristic["assistant_role"],
                "id_column": id_col,
                "title_column": title_col,
                "category_column": cat_col,
                "aliases_column": alias_col,
                "entity_keywords": entity_keywords,
                "clarification_prompt": llm_plan.get("clarification_prompt") or heuristic["clarification_prompt"],
                "system_prompt_rules": llm_plan.get("system_prompt_rules") or heuristic["system_prompt_rules"],
                "answer_template": llm_plan.get("answer_template") or heuristic["answer_template"],
            }

        # Lưu cấu hình vào config.yaml
        self._sync_config(final_plan)

        return {
            "column_mapping": {
                "id_column": final_plan["id_column"],
                "title_column": final_plan["title_column"],
                "category_column": final_plan["category_column"],
                "aliases_column": final_plan["aliases_column"],
            },
            "entity_keywords": final_plan["entity_keywords"],
            "system_prompt_rules": final_plan["system_prompt_rules"],
            "answer_template": final_plan["answer_template"],
            "clarification_prompt": final_plan["clarification_prompt"],
        }

    def _sync_config(self, plan: dict[str, Any]) -> None:
        """
        Ghi toàn bộ cấu hình mới và prompt do LLM sinh ra vào config.yaml của domain.
        Bảo vệ không ghi đè administrative_procedures.
        """
        if self.domain_id == "administrative_procedures":
            return

        config_path = DOMAINS_DIR / self.domain_id / "config.yaml"
        if not config_path.exists():
            return

        try:
            current_cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

            # Cập nhật tên, mô tả, vai trò nếu trước đó sơ sài
            if plan.get("domain_name") and not current_cfg.get("domain_name"):
                current_cfg["domain_name"] = plan["domain_name"]
            if plan.get("description") and (not current_cfg.get("description") or len(current_cfg.get("description")) < 15):
                current_cfg["description"] = plan["description"]
            if plan.get("assistant_role") and not current_cfg.get("assistant_role"):
                current_cfg["assistant_role"] = plan["assistant_role"]

            # Đồng bộ entity keywords
            existing_kws = current_cfg.get("entity_keywords", [])
            new_kws = plan.get("entity_keywords", [])
            combined_kws = list(dict.fromkeys(existing_kws + new_kws))
            current_cfg["entity_keywords"] = combined_kws

            # Đồng bộ prompt rules và answer template
            current_cfg["clarification_prompt"] = plan.get("clarification_prompt", "")
            current_cfg["system_prompt_rules"] = plan.get("system_prompt_rules", "")
            current_cfg["answer_template"] = plan.get("answer_template", "")

            # Cấu hình chunk_fields tối giản: 1 chunk tổng quan chung
            current_cfg["chunk_fields"] = ["general"]
            current_cfg["chunk_field_specs"] = {
                "general": {
                    "suffix": "_general",
                    "label": "Thông tin chi tiết",
                    "attr": "content",
                }
            }

            with open(config_path, "w", encoding="utf-8") as fp:
                yaml.dump(current_cfg, fp, allow_unicode=True, sort_keys=False)

            # Cập nhật thuộc tính runtime của self.config
            self.config.entity_keywords = combined_kws
            self.config.clarification_prompt = current_cfg["clarification_prompt"]
            self.config.system_prompt_rules = current_cfg["system_prompt_rules"]
            self.config.answer_template = current_cfg["answer_template"]
            self.config.chunk_fields = ["general"]
            self.config.chunk_field_specs = current_cfg["chunk_field_specs"]

            print(f"[ai_chunk_planner][{self.domain_id}] Synced config: Auto-prompt rules and templates updated successfully.")
        except Exception as e:
            print(f"[ai_chunk_planner][{self.domain_id}] Warning syncing config.yaml: {e}")
