# Đánh giá chất lượng AI, 07/11/2026

Cập nhật cho [README_EVALUATION.md](../README_EVALUATION.md) (đợt 22/10). Báo cáo này không phải kiểm định pháp lý.

## Kết luận

- Số 99–100% đo trên bộ golden **không phản ánh câu hỏi mới**: trên tập holdout mới, Field Match còn 84,2% và 20% câu hợp lệ bị từ chối nhầm.
- Rò rỉ claim `unsupported` không còn xuất hiện (0/12 qua API), nhưng cái giá là từ chối nhầm tăng: **10,5% câu trong bộ golden** bị trả "chưa có đủ thông tin" dù đã tìm đúng tài liệu.
- Từ chối câu ngoài phạm vi đã tốt lên thật: 92,5% trên chủ đề chưa từng được đưa vào blocklist.

## Kết quả

Mode `pipeline` chạy toàn bộ luồng có LLM, là mode gần với người dùng thật nhất. Mode `two_step` không gọi LLM sinh câu trả lời.

| Tập | Mode | Số câu | Retrieval@5 | Field Match | OOS từ chối đúng | Từ chối nhầm |
|---|---|---:|---:|---:|---:|---:|
| Golden | `two_step` | 100 | 98,9% | 98,9% | 5/5 | 1/95 = 1,1% |
| Golden | `pipeline` | 100 | 100% | 100% | 5/5 | **10/95 = 10,5%** |
| Golden + `task/oos_extra_cases.json` | `two_step` | 160 | 99,1% | 99,1% | 45/45 | 1/115 = 0,9% |
| **Holdout mới** | `two_step` | 60 | 85,0% | 78,9% | 37/40 = 92,5% | 2/20 = 10% |
| **Holdout mới** | `pipeline` | 60 | 90,0% | 84,2% | 37/40 = 92,5% | **4/20 = 20%** |

Đánh giá 12 ca qua API thật (cùng câu hỏi với đợt 22/10, trên Postgres local): 12/12 hoàn tất, 0 lỗi, đúng tài liệu 7/7, p50 1,55 giây, p95 1,96 giây.

Độ đầy đủ theo `expected_keywords` (golden, `pipeline`): 96/105 = 91,4%; 7/85 câu trả lời thiếu ít nhất một từ khóa.

## Cách đọc các số này

**Tập holdout.** `domains/administrative_procedures/holdout_cases_20261107.json` gồm 40 câu ngoài phạm vi và 20 câu trong phạm vi viết kiểu văn nói, không dấu. Chủ đề ngoài phạm vi được chọn không trùng blocklist, nhãn chốt trước khi chạy và không sửa theo kết quả. 60 câu là mẫu nhỏ: chỉ xem như chỉ báo. Không dùng tập này để tinh chỉnh, nếu không nó mất giá trị; hãy tạo tập `dev` riêng.

**Vì sao bộ golden bị thổi phồng.** `out_of_scope_topics` (54 mục) chứa nguyên chủ đề của bộ test, như `hàng không vũ trụ`, `nấu phở`, `tần số vô tuyến`, kể cả các câu thuộc split `held_out` trong `task/oos_extra_cases.json`. Tập đó vì vậy không còn độc lập.

**Chỉ số `unsupported` yếu.** `evidence_list` chỉ chứa claim đã qua bộ lọc, nên "0 rò rỉ" gần như đúng theo cấu trúc, không phải bằng chứng độc lập. Đúng/sai về nội dung vẫn cần người kiểm tra.

**Không so sánh độ trễ với đợt 22/10.** Lượt này phần lớn đi qua Fast Path, môi trường DB và máy cũng khác.

## Vấn đề cần xử lý

1. **Từ chối nhầm ở bước verify (ưu tiên cao).** Cả 10 ca golden đều hỏi về hồ sơ và đều đã xếp đúng tài liệu ở hạng 1: `GS_011, 022, 027, 030, 050, 060, 062, 065, 075, 090`. Riêng `GS_062` đi qua Fast Path, tức câu trả lời dựng trực tiếp từ bằng chứng mà vẫn bị từ chối, nên nghi vấn là `verify_answer` hoặc `filter_answer_by_verification` quá chặt với danh sách hồ sơ. **Chưa xác nhận nguyên nhân.**
2. **Bỏ claim `partial`.** Có thể làm danh sách hồ sơ thiếu mà trông như đầy đủ; với thủ tục hành chính, thiếu giấy tờ cũng gây hậu quả thực tế. Nên hiển thị thông báo khi câu trả lời bị cắt bớt.
3. **Lọt qua cổng phạm vi.** `HO_OOS_01` (nhận con nuôi, trùng từ với `nhận cha mẹ con`), `HO_OOS_30` (mèo con mới đẻ, gán vào PROC_018), `HO_OOS_35` (kể chuyện cười, gán vào PROC_004).
4. **Câu văn nói.** `HO_IN_03` (vợ người Hàn), `HO_IN_12` (lớp 7 chuyển trường) không tìm đúng tài liệu; `HO_IN_05` chọn sai trường thông tin.
5. **Lỗi hạ tầng bị che.** Khi DNS tới Qdrant lỗi, retrieval trả danh sách rỗng và người dùng nhận "chưa có đủ thông tin" như thể không có dữ liệu. Một lượt eval đã bị hỏng vì lỗi này (đã loại và chạy lại). Nên phân biệt "không có dữ liệu" với "hệ thống đang lỗi".
6. **Thay blocklist bằng cách tổng quát hơn.** Danh sách từ khóa cần sửa tay mỗi khi có chủ đề mới.

## Mục tiêu đề xuất (cần nhóm chốt)

| Chỉ số | Mục tiêu | Holdout `pipeline` hiện tại |
|---|---:|---:|
| OOS từ chối đúng | ≥ 90% | 92,5%, đạt |
| Từ chối nhầm | ≤ 3% | 20%, chưa đạt |
| Field Match | ≥ 85% | 84,2%, gần đạt |

## Tái lập

Từ `multi_domain_system/`, cần Qdrant và llama-server đang chạy:

```powershell
python scripts/eval_golden_set.py --mode pipeline --split all --save-report
python scripts/eval_golden_set.py --mode pipeline --extra-cases domains/administrative_procedures/holdout_cases_20261107.json --split held_out --save-report
python scripts/run_extended_evaluation.py --url http://127.0.0.1:8002 --out-dir docs/extended_evaluation_YYYYMMDD
```

Trước khi tin một lượt chạy, kiểm tra log không có `Qdrant query_points error` hoặc `is not available`.

Kết quả gốc: `docs/eval_20261107/`, `docs/extended_evaluation_20261107/`.
