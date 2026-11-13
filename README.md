# Day 06 · Data Ingestion Engineering

**Lab cá nhân** · **4 giờ** · **Dữ liệu tự chọn**

Biến tài liệu thành kho tri thức có thể truy xuất cho AI agent, rồi đo xem cách chuẩn bị dữ liệu nào hiệu quả nhất.

| 📄 Dữ liệu | 🧩 Chiến lược | 🎯 Benchmark |
|---|---|---|
| Tối thiểu **30 trang nội dung** | Tối thiểu **3 cấu hình** | Tối thiểu **20 câu hỏi** |

## Bắt đầu nhanh

Dùng [starter PostgreSQL + pgvector](starter/README.md) để dựng database và hoàn thiện các hàm TODO, hoặc tự chọn vector store tương đương. Starter chỉ là khung: **bạn tự hiện thực pipeline và benchmark**.

## 1. Xây pipeline

![Đọc tài liệu, chuẩn hóa, chia chunk, tạo vector, lưu và kiểm tra](assets/ingestion-pipeline.svg)

Chọn tài liệu được phép sử dụng; giữ **ID tài liệu, nguồn, trang/vị trí** và metadata phù hợp. Dùng embedding model thật qua API hoặc chạy local; lưu và truy xuất bằng pgvector, Qdrant, Chroma hoặc một store tương đương.

## 2. So sánh và đánh giá

![Ba chiến lược được đánh giá trên cùng corpus và benchmark dev/test](assets/benchmark-workflow.svg)

Dùng cùng dữ liệu, model và câu hỏi cho cả ba cấu hình. Tách **15 câu dev / 5 câu test** trước khi chạy; chọn cấu hình trên dev, rồi đánh giá test sau khi cố định. Mỗi câu hỏi cần có đoạn bằng chứng và trang nguồn; thiết kế bộ câu hỏi và đánh giá theo [BENCHMARK.md](BENCHMARK.md).

Đánh giá theo năm khía cạnh: **độ chính xác truy xuất**, **tính mạch lạc của chunk**, **tính hữu dụng của metadata**, **chất lượng grounding** và **tác động của chiến lược dữ liệu**. Giải thích lựa chọn bằng kết quả, ví dụ lỗi và các đánh đổi.

## 3. Chuẩn bị bài nộp

1. Chạy pipeline và lưu cấu hình, kết quả top-3, trace cùng nhãn đánh giá thủ công.
2. Điền [thông tin học viên](STUDENT.md), [nhật ký thí nghiệm](artifacts/experiment_log.csv) và bản sao [mẫu báo cáo cá nhân](report/individual/MSSV_HoTen.md).
3. Kiểm tra mã nguồn, cách chạy, manifest dữ liệu và checklist trong [SUBMISSION.md](SUBMISSION.md).

## Tài liệu hướng dẫn

| Bạn cần tìm | Tài liệu |
|---|---|
| Setup baseline PostgreSQL + pgvector | [starter/README.md](starter/README.md) |
| Các bước làm và cách tính chỉ số | [GUIDE.md](GUIDE.md) |
| Tiến độ trong 4 giờ | [CHECKPOINTS.md](CHECKPOINTS.md) |
| Năm tiêu chí benchmark và bộ câu hỏi | [BENCHMARK.md](BENCHMARK.md) |
| Tiêu chí chấm điểm | [RUBRIC.md](RUBRIC.md) |
| Quy tắc sử dụng dữ liệu, AI và API | [RULES.md](RULES.md) |
| Cách nộp bài | [SUBMISSION.md](SUBMISSION.md) |

[data/format-example.json](data/format-example.json) chỉ minh họa định dạng, không phải corpus đủ điều kiện. Phần xử lý và benchmark do bạn tự hiện thực; không bắt buộc xây chatbot.

---

## Bài làm của học viên: cách chạy lại

Corpus: 43 trang tài liệu Kubernetes (CC BY 4.0). Embedding chạy local: `intfloat/multilingual-e5-small` (384 chiều, CPU, $0). Vector store: PostgreSQL 16 + pgvector, tìm kiếm cosine chính xác. Báo cáo nằm ở [report/individual/2A202603527_TrinhCongDuc.md](report/individual/2A202603527_TrinhCongDuc.md).

| Đường dẫn | Nội dung |
|---|---|
| [data/](data/README.md) | `pages/` (43 trang đã làm sạch), `manifest.json`/`.csv`, giấy phép, nguồn gốc và cách dựng lại corpus |
| [benchmark/](benchmark/README.md) | 30 câu (22 dev / 8 test), evidence đã kiểm chứng, `FREEZE.json` (chốt trước mọi thí nghiệm) |
| `starter/src/` | pipeline: `ingestion`, `chunking`, `embeddings`, `store`, `evaluation`, `run`, `config` |
| `starter/scripts/` | dựng corpus, kiểm chứng benchmark, chọn mẫu coherence, audit metadata, sinh bảng tổng hợp |
| `starter/tests/` | unit test: bất biến của chunk, chuẩn hóa, cách tính metric |
| `results/` | thống kê ingest, metric dev/test, trace top-3, nhãn audit, log lỗi, môi trường chạy |
| [artifacts/experiment_log.csv](artifacts/experiment_log.csv) | cấu hình, giả thuyết và kết quả A/B/C (+ đối chứng A2) |

```bash
cd starter
python3 -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r requirements-embedding.txt
cp .env.example .env                                       # EMBEDDING_MODEL đã điền sẵn
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py                              # kiểm tra PostgreSQL + pgvector
python -m unittest discover -s tests -t .                  # 15 test
python -m src.run validate                                 # đọc, chuẩn hóa, log từng trang
python -m src.run ingest                                   # A, B, C, A2 → pgvector (vài phút trên CPU; lần đầu tải model ~470 MB)
python -m src.run evaluate --split dev
python -m src.run evaluate --split test                    # bị chặn nếu chưa có results/selection_decision.md
python -m src.run reingest-check                           # nạp lại không nhân đôi, tài liệu đổi/xóa
python scripts/audit_metadata.py --split test
python scripts/make_summary_tables.py                      # results/summary_tables.md
python scripts/verify_submission.py                        # kiểm tra lại mọi yêu cầu nộp bài (chỉ đọc, không ghi đè kết quả)
```
