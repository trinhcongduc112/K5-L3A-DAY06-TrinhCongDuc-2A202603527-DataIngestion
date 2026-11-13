# Báo cáo cá nhân — Day 6

**Học viên:** Trịnh Công Đức · MSSV 2A202603527 · Lớp L3A
**Corpus:** Kubernetes Concepts (Workloads + Services/Networking), 43 trang, CC BY 4.0
Mọi con số dưới đây lấy từ file kết quả trong `results/`. Bảng đầy đủ do script sinh ra nằm ở [results/summary_tables.md](../../results/summary_tables.md).

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang.**
  - Nguồn: tài liệu khái niệm chính thức của Kubernetes, repo `kubernetes/website`, commit `fe0b20298483…` (là HEAD lúc truy cập ngày 2026-11-13). Giấy phép CC BY 4.0, đã đối chiếu với file `LICENSE` của repo; ghi công "© The Kubernetes Authors".
  - Quy mô: 43 trang, gồm 11 trang `services-networking` và 32 trang `workloads`.
  - Quy tắc tính trang: tài liệu là Markdown không phân trang, nên **mỗi trang khái niệm là một đơn vị nguồn độc lập**. Trang ngắn nhất có 2.326 ký tự sau chuẩn hóa (≥ 1.500), không trang nào trùng nội dung.
  - Kích thước: 622.448 ký tự gốc, còn 619.252 ký tự sau chuẩn hóa.
  - Quy tắc chọn: lấy trang tiếng Anh của hai mục trên, loại `_index.md` và trang dưới 1.500 ký tự.
  - Manifest [data/manifest.json](../../data/manifest.json) ghi URL, đường dẫn repo, permalink, git blob SHA-1, giấy phép, ngày truy cập và số ký tự của từng trang.
  - Tái lập: dựng lại corpus từ commit đã ghim cho kết quả **giống hệt từng byte** với bản đang dùng; cách làm ở [data/README.md](../../data/README.md).
- **Chuẩn hóa, lỗi và giới hạn.**
  - Các bước chuẩn hóa: Unicode NFC, NBSP thành dấu cách, bỏ khoảng trắng cuối dòng, gộp dòng trống, bỏ id heading `{#…}` của Hugo (131 chỗ) và 9 dòng `<a id>` đứng riêng.
  - Khôi phục 42 heading rỗng ("What's next" / "Before you begin"); đối chiếu với shortcode gốc thì khớp 42/42.
  - Code block được giữ nguyên.
  - Log từng trang ở `results/logs/ingestion_pages.jsonl`: 0 trang lỗi, rỗng hay cảnh báo. Lỗi gặp khi chạy và cách xử lý ghi trong [results/logs/errors.md](../../results/logs/errors.md).
  - Giới hạn do bước làm sạch gốc gây ra:
    - mất 41 ví dụ YAML (`code_sample`) và 92 dòng `feature-state`;
    - vài câu mất số phiên bản (ví dụ "As of Kubernetes , …"); benchmark không dùng các câu này;
    - 7 trang `_index.md` bị loại, trong đó có trang "Pods" (21.292 ký tự), cùng `service-traffic-policy.md` (1.491 ký tự).
- **Embedding, vector store, metric, lệnh chạy và chi phí.**
  - Model: `intfloat/multilingual-e5-small`, chạy bằng Sentence Transformers 6.3.0, revision `614241f6…`, 384 chiều, context 512 token, local trên CPU.
  - Xử lý input: query có tiền tố `query: `, document có tiền tố `passage: `, vector được chuẩn hóa. Cả bốn cấu hình dùng chung model này.
  - Vector store: PostgreSQL 16.16 + pgvector 0.8.7 (Docker `pgvector/pgvector:0.8.7-pg16`), bảng `chunks` với khóa `(strategy, chunk_id)`.
  - Tìm kiếm: metric cosine (`<=>`), **tìm kiếm chính xác**, không dùng index ANN.
  - Lệnh chạy (từ `starter/`): `python -m src.run validate | ingest | evaluate --split dev | evaluate --split test | reingest-check`. Chi tiết ở README gốc.
  - Chi phí: **$0**, không gọi API nào.
  - Môi trường: CPU i5-12500H 16 luồng, không GPU, Python 3.12.3, torch 2.15.0+cpu. Phiên bản thư viện ghim trong `starter/requirements-embedding.txt` và `results/environment.json`.
- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn.**
  - Metadata của mỗi chunk:
    - `document_id` và `source` (URL kubernetes.io);
    - `page` = thứ tự khối H2 trong trang (1 = phần mở đầu);
    - `heading_path`;
    - `char_start`/`char_end`: chunk luôn là lát cắt nguyên văn của trang đã chuẩn hóa;
    - `title` và `source_version` (git blob SHA).
  - Trường lọc: `section` (2 giá trị) và `subsection` (7 giá trị). Giá trị lấy từ **đường dẫn thư mục trong repo**, không phải đoán.
  - Lý do chọn: corpus có những chủ đề trùng tên ở các mục khác nhau, ví dụ priority của Pod và của PodGroup, topology routing và topology scheduling, policy types và NetworkPolicy.

## Cấu hình và benchmark

- **A / B / C (tham số cụ thể, khác biệt duy nhất B–C).**

  | | Chunking | Kích thước | Truy xuất |
  |---|---|---|---|
  | A | Cửa sổ cố định; điểm cắt được lùi về khoảng trắng để không cắt giữa từ | 500 ký tự, overlap 50 | Không lọc |
  | B | Theo heading/đoạn: không cắt đoạn, danh sách hay code block; luôn tách ở H2; tách ở H3+ khi chunk đã ≥ 300 ký tự; khối > 1.000 ký tự được chia theo thứ tự ưu tiên xuống dòng > hết câu > khoảng trắng | ≤ 1.000 (cộng tối đa một dòng heading) | Không lọc |
  | C | **Đúng chunk và vector của B** | như B | Lọc `section`/`subsection` cho 6/30 câu có filter; câu không có filter chạy y như B |
  | A2 (đối chứng, không dự tuyển) | như A | 1.000 ký tự, overlap 100 | Không lọc |

  Khác biệt duy nhất giữa B và C là mệnh đề `WHERE` theo metadata. A2 có cùng trần kích thước với B, dùng để tách ảnh hưởng của *kích thước* khỏi ảnh hưởng của *ranh giới*.
- **≥ 20 câu: phân chia dev/test, câu metadata filter và cách kiểm chứng evidence.**
  - Quy mô: 30 câu tiếng Anh, gồm **22 dev và 8 test**, tách theo tài liệu nên không tài liệu gold nào xuất hiện ở cả hai tập.
  - Loại câu ở dev: 6 trực tiếp, 6 diễn đạt lại, 6 điều kiện/ngoại lệ, 4 cần metadata. Ở test: mỗi loại 2 câu.
  - **6 câu có filter**: 4 ở dev (d18–d21) và 2 ở test (t06, t07). Filter là ngữ cảnh người dùng cung cấp (khu vực tài liệu đang đọc), luôn chứa tài liệu gold, không nêu tên nó, và có phạm vi 4–32 tài liệu.
  - Kiểm chứng evidence bằng `starter/scripts/build_benchmark.py`:
    - 30/30 evidence xuất hiện đúng một lần trong văn bản đã chuẩn hóa;
    - quét câu gần trùng trên toàn corpus;
    - d07 và d08 có hai nguồn hợp lệ, được ghi cả hai;
    - các trường `gold_page`, `gold_heading` và offset được suy ra bằng script, không gõ tay.
  - Benchmark được chốt bằng SHA-256 lúc **11:17:54 UTC**, trước mọi embedding và truy vấn. `run.py` từ chối đánh giá nếu file bị đổi. Chi tiết ở [benchmark/README.md](../../benchmark/README.md).
- **Tiêu chí chọn chiến lược, chốt trước khi xem test** ([selection_criteria.md](../../results/selection_criteria.md), viết lúc 11:21:14 UTC, trước mọi truy vấn).
  - Thứ tự xét trên dev: Hit@3 → Hit@1 → tài nguyên.
  - C chỉ thắng B nếu tốt hơn rõ ràng; chênh lệch ≤ 1 câu được coi là nhiễu.
  - A2 không được chọn.
  - Tập test chỉ chạy được sau khi đã có [selection_decision.md](../../results/selection_decision.md) (11:31:57 UTC). Test chạy đúng một lần lúc 11:32:20 UTC.

## Kết quả

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian ingest | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 5/22 | 11/22 | 1.393 | 88,2 s | $0 |
| A | test | 2/8 | 4/8 | 1.393 | (như trên) | $0 |
| **B (chọn)** | dev | 11/22 | 18/22 | 967 | 79,2 s | $0 |
| **B (chọn)** | test | 3/8 | 6/8 | 967 | (như trên) | $0 |
| C | dev | 12/22 | 18/22 | 967 (chung với B) | 0,4 s (dùng lại vector của B) | $0 |
| C | test | 3/8 | 6/8 | 967 | (như trên) | $0 |
| A2 (đối chứng) | dev | 9/22 | 15/22 | 704 | 85,1 s | $0 |
| A2 (đối chứng) | test | 2/8 | 6/8 | 704 | (như trên) | $0 |

- Thời gian ingest = chia chunk + embed + ghi DB trên CPU. Phần embed chiếm hơn 99%. Thời gian nạp model (15,2 s) tính riêng.
- Truy vấn mất 30–47 ms/câu (median), C không chậm hơn B.
- Không chunk nào vượt 512 token (lớn nhất 399).
- MRR@3: dev A 0,356, B 0,652, C 0,682, A2 0,538; test A 0,354, B và C 0,542, A2 0,479.

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 0,90 (10) | 16/24 (24/24 nếu chỉ xét điểm bắt đầu chunk) | test 2/2 · dev 1/4 | 3/0/5 · 1,25 |
| B | 1,70 (10) | 24/24 | test 2/2 · dev 3/4 | 2/0/6 · 1,50 |
| C | 1,70 (10, cùng chunk với B) | 24/24 | test 2/2 · dev 4/4 | 2/0/6 · 1,50 |
| A2 | 1,00 (10) | 8/24 (24/24 nếu chỉ xét điểm bắt đầu) | test 2/2 · dev 2/4 | 1/0/7 · 1,75 |

**Đường dẫn trace, nhãn thủ công và cách chọn mẫu.**
- Trace top-3 đầy đủ (câu hỏi, filter, ID và text chunk, score, metadata, trạng thái từng chunk): `results/traces/{dev,test}_{A,B,C,A2}.jsonl`. Metric nằm ở `results/metrics_{dev,test}.json`.
- **Coherence:** `results/audit/coherence_{positions.json,samples.csv,labels.csv}`.
  - 10 vị trí được `make_coherence_samples.py` chọn với seed 20261113: 3 ở services-networking, 7 ở workloads, mỗi vị trí là điểm giữa của một đoạn ≥ 200 ký tự.
  - Nhãn được viết lúc 11:28:57 UTC, **trước khi chạy bất kỳ truy vấn nào**.
- **Metadata:** `results/audit/metadata_audit_test.csv`. Script đối chiếu cả 24 bản ghi top-3 của mỗi chiến lược với trang nguồn:
  - URL, `section` và `subsection` so với manifest;
  - text so với lát cắt `[char_start:char_end]`;
  - `heading_path` và `page` so với heading gốc;
  - chunk có vắt qua ranh giới H2 hay không.
- **Grounding:** `results/audit/grounding_labels_test.csv`, gồm cả 8 câu test × 4 chiến lược, có lý do cho từng nhãn.
- Rubric và người chấm: [results/audit/README.md](../../results/audit/README.md).
- Chẩn đoán sau sự việc: sau khi đánh giá test, `starter/scripts/diagnose_misses.py` tìm hạng của chunk chứa evidence trong top-50 cho các câu trượt, tỷ lệ chunk vắt qua H2, mức độ bao phủ evidence và so sánh ghép cặp (McNemar). Kết quả ở `results/diagnostics_misses.json`. Bước này chỉ để phân tích lỗi; không tham số, cấu hình hay benchmark nào bị thay đổi.
- Bằng chứng về nạp lại:
  - Ingest lần 2 trên dữ liệu thật: `inserted=0, updated=1.393/967, deleted=0`.
  - `results/reingest_check.json`: trang bị sửa có 5 chunk cũ bị xóa và 5 chunk mới được thêm; trang bị bỏ khỏi corpus có 8 chunk bị xóa.

## Phân tích và kết luận

**1. Độ chính xác truy xuất.**
- So với A, B tăng Hit@3 dev từ 11 lên 18 và Hit@1 từ 5 lên 11. Trên test, Hit@3 tăng từ 4 lên 6 và Hit@1 từ 2 lên 3.
- So ghép cặp từng câu: có 11 câu B đúng mà A sai (9 dev, 2 test) và chỉ 2 câu ngược lại (d09, d22). Kiểm định McNemar chính xác cho p ≈ 0,065 trên riêng dev và p ≈ 0,022 khi gộp dev với test.
- Nguyên nhân mang tính cấu trúc: số câu có evidence nằm trọn trong *một* chunk là A 24/30, A2 28/30, B 30/30. Với A, 6 câu (d01, d10, d14, d21, t06, t08) không bao giờ thành hit dù tăng k, và 6/11 câu A trượt ở dev là `evidence_split`.
- Đối chứng A2 (cùng trần 1.000 ký tự như B) lấy lại được một phần khoảng cách: Hit@3 dev 15/22. Tuy vậy, B so với A2 là 5 câu so với 2, p ≈ 0,45. Vì vậy **chưa đủ bằng chứng nói rằng ranh giới theo cấu trúc tốt hơn kích thước lớn về Hit@3**; khác biệt rõ chỉ thấy ở coherence và metadata.

**2. Tính mạch lạc của chunk.**
- Điểm trung bình: B 1,70, A 0,90, A2 1,00.
- A2 lớn gấp đôi A nhưng coherence gần như không tăng, vì cắt cứng vẫn để lại mảnh câu ở hai đầu: cả 10 mẫu A2 đều được 1 điểm.
- B mất điểm ở 3/10 vị trí:
  - c03: câu dẫn của danh sách bị dồn sang chunk trước;
  - c09: câu dẫn ở cuối chunk còn danh sách nằm ở chunk sau;
  - c07: chính nguồn có một câu bị code block chia đôi.

**3. Tính hữu dụng của metadata.**
- Đủ và đúng: B/C 24/24, A 16/24, A2 8/24. Nguyên nhân: 21% chunk của A và 37% chunk của A2 vắt qua ranh giới H2, nên `page`/`heading_path` chỉ đúng cho phần đầu chunk. B không có chunk nào vắt qua ranh giới.
- Trường hữu ích:
  - `heading_path` cộng offset giúp truy đúng đoạn nguồn, ví dụ t05 → "Hostname with pod's hostnameOverride", ký tự 3.300–3.442.
  - `subsection` sửa được d20, như phân tích ở mục B–C bên dưới.
- Hạn chế:
  - `section` quá thô: filter của d21 phủ 32 tài liệu nên không làm đổi kết quả nào.
  - `subsection="(root)"` là giá trị đặt thay, không phải một mục thật.
  - Filter giả định người dùng cung cấp phạm vi trước khi truy xuất.
  - Trên test, 2/2 câu có filter đã tuân thủ phạm vi ngay cả khi không lọc, nên test **không đo được** lợi ích của filter.

**4. Grounding.** Đây là đánh giá bằng chứng được truy xuất, không phải độ chính xác câu trả lời của LLM.
- Điểm trung bình: B/C 1,50, A 1,25, A2 1,75.
- B đủ bằng chứng ở 6/8 câu. Hai câu được 0 (t03, t06) đều do lấy đúng tài liệu nhưng sai đoạn; evidence nằm ở hạng 8 và 5.
- A2 nhỉnh hơn B một câu (t06) nhờ ghép được vế điều kiện và vế hệ quả qua hai chunk. Với n = 8, mức chênh này nằm trong nhiễu.
- Nhãn thủ công chấp nhận bằng chứng tương đương. Ví dụ t08-A được 2 dù Hit tự động tính là trượt, vì chunk chỉ thiếu 2 từ cuối.

**5. Tác động của chiến lược dữ liệu (A–B, B–C) và tài nguyên.**
- **A → B (thay chunking).**
  - Tài nguyên: ít hơn 31% chunk (967 so với 1.393), ít ký tự phải embed hơn (617k so với 679k vì không overlap), embed nhanh hơn khoảng 10% (79 s so với 88 s).
  - Chất lượng: tốt hơn ở cả năm khía cạnh.
  - Đánh đổi: kích thước chunk của B dao động 43–1.027 ký tự (8 chunk dưới 100 ký tự, chủ yếu mục "What's next"), và câu dẫn có thể bị tách khỏi danh sách.
- **B → C (chỉ thêm filter).**
  - Tài nguyên: không tốn thêm (cùng index, chỉ thêm `WHERE`).
  - Dev: chỉ **d20** thay đổi. B xếp trang *PodGroup priority* (workload-api) ở hạng 1–2; filter `pods` đưa chunk gold `advanced-pod-config@163-804` lên hạng 1. Tuân thủ phạm vi tăng từ 3/4 lên 4/4.
  - Test: top-3 giống hệt B ở cả 8 câu.
  - Kết luận: filter đúng phạm vi không làm kết quả tệ đi, nhưng chỉ có ích khi tài liệu gây nhầm nằm *ngoài* phạm vi.

**Hai ví dụ sai.**
1. **t08 (test), chiến lược A: evidence bị cắt.**
   - Câu hỏi: những ingress controller nào do chính dự án Kubernetes hỗ trợ.
   - Chunk hạng 1 `k8s-services-networking-ingress-controllers@0-497` dừng đúng ở "…supports and maintains AWS, and GCE"; phần " ingress controllers." nằm ở chunk sau.
   - Hit tự động tính là trượt (`evidence_split`), dù người đọc vẫn trả lời được (grounding 2).
   - B giữ trọn mục "Ingress controllers" trong một chunk 104 ký tự (`@414-518`) và xếp nó hạng 1.
2. **t03 (test), chiến lược B và C: đúng tài liệu, sai đoạn.**
   - Câu hỏi: "…can it also share the node's network namespace?"
   - Cả top-3 đều thuộc `k8s-workloads-pods-user-namespaces` nhưng là phần giới thiệu (`@4412-5100`, `@3275-4225`, `@2343-3273`).
   - Evidence "if you set `hostUsers: false` then you are not allowed to set any of: `hostNetwork: true` …" nằm ở mục *Limitations* (page 8, ký tự 12.441–12.572) và chỉ đứng **hạng 8**.
   - Lý do khả dĩ: đoạn evidence là danh sách tên trường, khó khớp với câu hỏi bằng ngôn ngữ tự nhiên trên một model nhỏ.
   - Thêm một ví dụ ở dev: d03 là câu diễn đạt lại, không chứa cụm "deletion cost", nên cả 4 chiến lược đều kéo về các đoạn chung chung về "scaling"; chunk gold của B đứng hạng 24.

**Chiến lược chọn, đánh đổi, điều kiện áp dụng.**
- Chọn **B** theo luật đã chốt: B và C bằng nhau về Hit@3; C hơn 1 câu Hit@1, nằm trong ngưỡng nhiễu nên coi là hòa; khi hòa thì ưu tiên B vì không cần ngữ cảnh filter.
- Tập test xác nhận cùng hướng: B 6/8 so với A 4/8 về Hit@3.
- Điều kiện áp dụng:
  - B phù hợp với tài liệu có cấu trúc heading rõ (Markdown/HTML).
  - Nên bật filter như C khi giao diện cung cấp phạm vi đáng tin, nhất là với những chủ đề trùng tên giữa các mục.
- Không suy rộng kết luận ra ngoài corpus này và model e5-small.

**Hạn chế.**
- Mẫu nhỏ: test chỉ có 8 câu; Hit@3 = 6/8 có khoảng tin cậy Wilson 95% rộng từ 41% đến 93%, nên chênh lệch 1–2 câu là nhiễu.
- Benchmark, pipeline và nhãn đều do cùng một trợ lý AI soạn. Điều này có nguy cơ thiên lệch, ví dụ câu hỏi vô tình hợp với cách chia chunk của B. Chỉ có một người chấm và chưa có người chấm thứ hai.
- Hit nghiêm ngặt có thể đánh giá thấp bằng chứng tương đương (như t08-A); nhãn grounding thủ công bù được một phần.
- Corpus mất ví dụ YAML và dòng feature-state, thiếu các trang `_index.md`, và chỉ có tiếng Anh.
- Thời gian chỉ đo một lần trên một máy, CPU dùng chung với các container khác. Tìm kiếm chính xác trên khoảng 1.000 dòng không đại diện cho quy mô lớn.
- Topic giữa dev và test vẫn gần nhau dù đã tách theo tài liệu. Ví dụ trang gây nhầm của d20 chính là tài liệu gold của t07.

**Nếu làm lại hoặc mở rộng.**
1. Gắn "tiêu đề trang > heading" vào đầu chunk B khi embed để những câu như t03, d22 dễ khớp hơn.
2. Giữ câu dẫn đi cùng danh sách ngay sau nó, để sửa các trường hợp như c03, c09.
3. Rerank top-10 bằng cross-encoder hoặc dùng hybrid BM25, vì evidence của mọi câu B trượt đều nằm ở hạng 5–8 (trừ d03 ở hạng 24).
4. Dùng model mạnh hơn (e5-base, bge-m3) và tập test lớn hơn có người chấm thứ hai.
5. Đưa lại các trang `_index.md` và ví dụ code vào corpus.

## Sử dụng AI và cách kiểm tra

**Công cụ:** Claude Code, trợ lý AI của Anthropic. Claude Code đã làm các việc sau:
- kiểm tra corpus nhận từ một phiên AI khác;
- viết code pipeline, script và test;
- soạn 30 câu benchmark;
- gán nhãn coherence và grounding;
- soạn bản nháp báo cáo này.

**Cách kiểm tra:**
- 15 unit test kiểm tra bất biến của chunk (lát cắt nguyên văn, bao phủ 100%, không cắt giữa từ, không vắt qua H2) và cách tính metric.
- Corpus dựng lại từ commit đã ghim cho kết quả giống hệt từng byte.
- Script kiểm chứng benchmark báo 0 lỗi và 0 cảnh báo.
- Bước kiểm tra nạp lại đạt cả ba tiêu chí.
- Audit metadata đối chiếu với nguồn bằng script.
- Rà lại toàn văn mọi nhãn grounding 0/1 phát hiện 2 nhãn chấm sai do đọc văn bản bị cắt (t08-A, t06-A2). Hai nhãn đã được sửa và ghi vào `errors.md`.

**Phần học viên cần tự làm trước khi nộp:**
- đọc lại 30 câu hỏi trong `benchmark/questions.csv`;
- rà soát và xác nhận từng nhãn (cột `student_review` trong `results/audit/*.csv`);
- nắm được cách pipeline hoạt động để giải thích khi được hỏi.
