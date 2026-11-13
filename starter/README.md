# Starter · PostgreSQL + pgvector

Bộ khởi động **tùy chọn** cho lab cá nhân. Docker Compose tạo PostgreSQL + pgvector local; các file trong `src/` là **khung pseudocode có TODO**, chưa đọc tài liệu, tạo embedding, lưu vector hay chạy benchmark. Bạn cần tự hiện thực. Vẫn có thể chọn Qdrant, Chroma hoặc vector store tương đương theo [GUIDE.md](../GUIDE.md).

> **Trạng thái bài làm:** mọi hàm TODO trong `src/` đã được hiện thực cho corpus Markdown Kubernetes (không có PDF nên `pypdf` không được dùng). Corpus, benchmark và kết quả nằm ở thư mục gốc `../data`, `../benchmark`, `../results` theo [SUBMISSION.md](../SUBMISSION.md); `starter/data/` và `starter/results/` để trống. Lệnh chạy đầy đủ: phần "Bài làm của học viên" trong [README gốc](../README.md).

## Cấu trúc

```text
starter/
├── docker-compose.yml          # PostgreSQL 16 + pgvector, chỉ mở cổng local
├── init.sql                    # bật extension khi tạo database mới
├── requirements.txt            # psycopg, pypdf và python-dotenv
├── requirements-embedding.txt  # torch (CPU), sentence-transformers: đúng phiên bản đã chạy
├── .env.example                # cấu hình mẫu; copy thành .env
├── scripts/
│   ├── check_setup.py          # kiểm tra kết nối và extension
│   ├── build_corpus.py         # dựng corpus + manifest từ kubernetes/website (xem ../data/README.md)
│   ├── build_benchmark.py      # kiểm chứng evidence, split, filter → ../benchmark/questions.json
│   ├── make_coherence_samples.py  # chọn 10 vị trí chấm coherence (seed cố định)
│   ├── audit_metadata.py       # đối chiếu metadata top-3 với nguồn
│   ├── make_summary_tables.py  # sinh ../results/summary_tables.md
│   ├── diagnose_misses.py      # phân tích sau sự việc: hạng của evidence khi trượt, McNemar
│   └── verify_submission.py    # kiểm tra toàn bộ yêu cầu nộp bài (chỉ đọc)
├── src/
│   ├── config.py               # đường dẫn + cấu hình chiến lược A/B/C (+ đối chứng A2)
│   ├── models.py               # DocumentPage, Chunk
│   ├── ingestion.py            # đọc corpus theo manifest, chuẩn hóa, log từng trang
│   ├── chunking.py             # fixed_size (A, A2) và by_paragraph (B, C)
│   ├── embeddings.py           # intfloat/multilingual-e5-small (local, có prefix query:/passage:)
│   ├── store.py                # pgvector: upsert không trùng, xóa chunk cũ, search cosine + filter
│   ├── evaluation.py           # Hit@1, Evidence Hit@3, phân loại lỗi, tổng hợp
│   └── run.py                  # validate / ingest / evaluate / reingest-check
├── tests/                      # unit test (python -m unittest discover -s tests -t .)
├── data/                       # (không dùng; corpus ở ../data)
└── results/                    # (không dùng; kết quả ở ../results)
```

## 1. Cài và kiểm tra database

Cần Docker Desktop hoặc Docker Engine + Compose, Python **3.11–3.14**, và mạng để tải image/dependencies lần đầu. Các lệnh sau chạy từ thư mục `starter/`:

```bash
cd starter
python3 -m venv .venv
```

Kích hoạt `.venv`: macOS/Linux dùng `source .venv/bin/activate`; Windows PowerShell dùng `.venv\Scripts\Activate.ps1`. Sau đó:

```bash
python -m pip install -r requirements.txt
# macOS/Linux: cp .env.example .env
# Windows PowerShell: Copy-Item .env.example .env
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py
```

Kỳ vọng: hiện tên database, phiên bản PostgreSQL và pgvector, sau đó `Setup OK`. Đây **chỉ là kiểm tra hạ tầng**, không phải kết quả benchmark. Docker dùng cổng `127.0.0.1:55433` và mật khẩu cố định **chỉ dùng local cho lab**; nếu cổng bận, sửa đồng thời port trong `docker-compose.yml` và `DATABASE_URL` trong `.env`. `init.sql` chỉ chạy khi volume mới được tạo; nếu database sẵn có chưa bật extension, xem log Docker và kiểm tra cấu hình thay vì xóa volume chứa dữ liệu.

Dừng container nhưng giữ dữ liệu:

```bash
docker compose -p day6_student_starter stop
```

## 2. Chọn embedding model

Điền key tương ứng trong `.env` nếu dùng OpenRouter, OpenAI hoặc Gemini; **không commit `.env`**. Model local không cần API key. `requirements.txt` chỉ có dependencies cơ bản: tự cài SDK hoặc thư viện local phù hợp với model bạn chọn và ghi lại version/lệnh cài trong báo cáo. Ghi tên model và số chiều; dùng cùng model cho toàn bộ chiến lược và vector query tương thích vector document.

## 3. Hoàn thiện pipeline

1. Đặt corpus vào `data/` hoặc cung cấp manifest/hướng dẫn truy cập. Đọc [GUIDE.md](../GUIDE.md) về **30 trang nội dung**, quyền dữ liệu và metadata.
2. Hoàn thiện từng hàm TODO trong `src/`. Lưu ID tài liệu, nguồn, trang/vị trí và ít nhất một trường filter có ích.
3. Xây ít nhất ba cấu hình; ví dụ A fixed-size, B theo đoạn, C như B nhưng có filter. Cần cùng corpus, model và benchmark; nạp lại không nhân đôi và xử lý chunk cũ khi dữ liệu đổi.
4. Tự viết ít nhất 20 câu hỏi kèm evidence, tách dev/test trước khi thử theo [BENCHMARK.md](../BENCHMARK.md). Lưu trace top-3 và báo cáo đủ năm tiêu chí.
5. Sau khi hoàn thiện, chạy `python -m src.run` từ thư mục `starter/`. Trước khi làm TODO, lệnh này **chủ động báo `NotImplementedError`**. *(Bài làm: lệnh này giờ chạy validate → ingest → evaluate trên tập dev; tập test chỉ chạy bằng `python -m src.run evaluate --split test` sau khi đã chốt lựa chọn.)*

Lưu code, cấu hình, kết quả và lệnh chạy để người chấm tái lập; không commit key, dữ liệu mật hoặc dữ liệu không có quyền chia sẻ.
