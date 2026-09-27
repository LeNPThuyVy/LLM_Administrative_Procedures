# Person 1 — Day 1 (2 tiếng): Benchmark → Chốt model → Quantize → Test nhanh

**Giả định:** máy local của bạn **không có GPU riêng** (model remote Qwen3-4B đang chạy qua Vast.ai tunnel, không phải máy bạn) → toàn bộ luồng dưới đây đi theo nhánh **CPU + GGUF Q4_K_M qua llama.cpp**, đúng với nhánh mà sprint plan liệt kê ưu tiên đầu tiên. Nếu thực ra bạn có GPU local, báo lại — nhánh AWQ sẽ nhanh hơn nhưng cài đặt khác hẳn (autoawq + CUDA), không nên trộn hai nhánh trong 2 tiếng.

**State hiện tại đã xác nhận từ code (`my_config.py`, `rag/generator.py`, `rag/hybrid_generator.py`):**
- Local fallback model: `Qwen/Qwen2.5-0.5B-Instruct`, load qua `transformers` (fp32 trên CPU), **chưa quantize**.
- Có sẵn `hybrid_generator.py`: thử remote Qwen3-4B trước, fallback về local 0.5B nếu remote lỗi. Việc bạn làm hôm nay **không đụng vào remote path** — chỉ chuẩn bị model local mới để thay thế nhánh fallback (Day 2 mới swap vào `generator.py`).
- **Chưa có `demo_questions.md` trong repo** — plan Day 1 có nhắc tới file này nhưng nó chưa tồn tại, nên bước đầu tiên là tự tạo nhanh.

---

## Phút 0–15 — Tạo bộ câu hỏi benchmark + đo model hiện tại

Không cần script phức tạp. Tạo file `demo_questions.md` với ~8 câu hỏi tiêu biểu (theo field: phí, thời hạn, cách nộp, giấy tờ — đúng 4 field mà `prompt_builder.py` đang detect), ví dụ:

```
1. Lệ phí làm căn cước công dân là bao nhiêu?
2. Thời gian giải quyết hồ sơ đăng ký kết hôn là bao lâu?
3. Nộp hồ sơ đăng ký tạm trú ở đâu và bằng cách nào?
4. Cần chuẩn bị giấy tờ gì để làm hộ chiếu?
5. Lệ phí và thời gian làm giấy khai sinh là bao nhiêu, mất bao lâu?  (câu hỏi ghép 2 field)
6. Thủ tục đăng ký kinh doanh hộ cá thể cần giấy tờ gì?
7. Tôi cần làm gì để xin giấy xác nhận tình trạng hôn nhân?
8. Thời hạn nộp hồ sơ gia hạn visa là khi nào?
```

Chạy nhanh qua **`generate_answer()`** trong `rag/generator.py` trực tiếp (không cần load toàn bộ pipeline + Chroma nếu chỉ muốn đo tốc độ raw model — nhưng nếu muốn đo chất lượng thật thì chạy qua `rag/pipeline.py::answer_query()` để có evidence RAG thật). Ưu tiên chạy qua pipeline thật nếu Chroma DB (`data/chroma_db`) đã có sẵn data, vì đó mới là chất lượng thực tế người dùng thấy.

Script đo nhanh (dán vào file `bench.py` ở root repo):

```python
import time
from rag.pipeline import answer_query  # hoặc hàm entrypoint tương ứng

questions = [...]  # copy từ demo_questions.md

for q in questions:
    t0 = time.time()
    resp = answer_query(q, session_id="bench")  # điều chỉnh theo signature thật
    dt = time.time() - t0
    print(f"[{dt:.1f}s] Q: {q}\nA: {resp}\n{'-'*40}")
```

Ghi lại: **latency trung bình/câu** + **RAM peak** (Task Manager / `htop`) + note chủ quan chất lượng (đúng trọng tâm không, có bịa không). Đây là baseline để Day 2 so sánh.

---

## Phút 15–25 — Chốt model đích + phương pháp quantize

**Quyết định (khuyến nghị, không cần họp lại vì đã nằm trong sprint plan):**

| | Quyết định | Lý do |
|---|---|---|
| Model đích | **Qwen2.5-1.5B-Instruct** | 0.5B hiện tại quá nhẹ → dễ trả lời sai trọng tâm/bịa; 3B nặng hơn cho CPU serving trong demo trực tiếp. 1.5B là điểm cân bằng tốt nhất cho tiếng Việt hành chính + tốc độ CPU khi có nhiều người dùng đồng thời trong buổi demo. |
| Phương pháp | **GGUF Q4_K_M qua llama.cpp** | Serve CPU (đúng giả định môi trường), Q4_K_M là sweet-spot chất lượng/dung lượng chuẩn của cộng đồng llama.cpp cho model cỡ 1–3B. |

Nếu benchmark ở bước trên cho thấy 0.5B hiện tại đã đủ tốt và nhanh, có thể cân nhắc quantize luôn 0.5B thay vì nhảy lên 1.5B — nhưng theo yêu cầu mentor ("nhẹ nhất, chất lượng nhất"), 1.5B quantized Q4_K_M vẫn nhẹ hơn nhiều so với 3B/7B mà chất lượng tiếng Việt tốt hơn hẳn 0.5B, nên đây vẫn là lựa chọn mặc định hợp lý.

---

## Phút 25–100 (~75 phút) — Setup pipeline quantization + chạy ngay

### 1. Cài llama.cpp (10 phút)
```bash
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp
pip install -r requirements.txt
cmake -B build
cmake --build build --config Release -j 4
```
(Nếu build cmake lỗi/thiếu compiler trên Windows, dùng WSL hoặc dùng bản `w64devkit` theo README của llama.cpp — đừng mất quá 10 phút vào việc này, nếu vướng thì báo ngay để đổi hướng.)

### 2. Tải model gốc từ HuggingFace (5–10 phút, tùy mạng)
```bash
pip install -U "huggingface_hub[cli]"
huggingface-cli download Qwen/Qwen2.5-1.5B-Instruct --local-dir ./qwen2.5-1.5b-instruct
```

### 3. Convert sang GGUF (f16 trung gian) (5 phút)
```bash
cd llama.cpp
python convert_hf_to_gguf.py ../qwen2.5-1.5b-instruct \
  --outfile qwen2.5-1.5b-instruct-f16.gguf \
  --outtype f16
```

### 4. Quantize xuống Q4_K_M (2–5 phút, nhanh)
```bash
./build/bin/llama-quantize \
  qwen2.5-1.5b-instruct-f16.gguf \
  qwen2.5-1.5b-instruct-Q4_K_M.gguf \
  Q4_K_M
```

Xong bước này bạn có file `qwen2.5-1.5b-instruct-Q4_K_M.gguf` (~1GB, so với f16 gốc ~3GB) — đây là artifact chính của Day 1.

### 5. Buffer 20–30 phút cho lỗi phát sinh
Các lỗi hay gặp: thiếu RAM khi convert (dùng máy có ít nhất 8GB free), sai `--outtype`, thiếu quyền build cmake. Đừng cố fix quá 15 phút một lỗi — nếu bí, ghi lại và hỏi ngay, đừng để trôi sang giờ 3.

---

## Phút 100–120 — Đo thử chất lượng lần đầu (so với baseline)

Chạy nhanh model quantized qua CLI (chưa cần tích hợp vào pipeline — đó là việc Day 2):

```bash
./build/bin/llama-cli -m qwen2.5-1.5b-instruct-Q4_K_M.gguf \
  -p "Bạn là trợ lý thủ tục hành chính. Lệ phí làm căn cước công dân là bao nhiêu?" \
  -n 256 --temp 0
```

Chạy qua 3–4 câu trong `demo_questions.md` (không cần hết 8 câu, để dành cho Day 2 verify đầy đủ), so sánh nhanh với output baseline ở bước 1:
- Có đúng trọng tâm câu hỏi không?
- Tốc độ sinh (token/s) có chấp nhận được không?
- Có lỗi định dạng/lặp từ không (dấu hiệu quantize quá aggressive)?

**Không cần tune calibration data hôm nay** — nếu chất lượng Q4_K_M đã ổn thì để nguyên, việc tune (nếu cần) đã nằm trong task Day 2 theo đúng phân công.

---

## Deliverable cuối Day 1 (để khớp với checklist sprint)
- [ ] `demo_questions.md` đã tạo, có baseline benchmark (latency + note chất lượng) của model hiện tại (Qwen2.5-0.5B unquantized)
- [ ] Model đích + phương pháp quantize đã chốt: Qwen2.5-1.5B-Instruct, GGUF Q4_K_M
- [ ] File `qwen2.5-1.5b-instruct-Q4_K_M.gguf` đã tạo thành công, chạy thử được qua `llama-cli`
- [ ] Note nhanh: chất lượng lần đầu ổn hay cần tune lại calibration/method cho Day 2

Lưu ý: **chưa cần sửa `generator.py`/`pipeline.py` hôm nay** — đúng theo phân công, việc tích hợp vào `pipeline.py::answer_query()` và không đổi input/output contract là việc của Day 2.
