# Báo cáo cá nhân — Day 6

> **Trạng thái:** phần truy xuất tự động (Hit@1, Evidence Hit@3, filter, chunk, thời gian) đã chạy xong ngày 14/11/2026. Ba bảng chấm thủ công (coherence, grounding, metadata) **chưa được chấm**; các ô liên quan ghi “chưa chấm”, không dùng số ước lượng. Corpus hiện có 23 trang, **chưa đạt mức tối thiểu 30 trang**.

## Dữ liệu và pipeline
- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:**
  - Chủ đề: Ngân hàng – mở thẻ. Tài liệu: *Điều khoản và điều kiện phát hành và sử dụng Thẻ tín dụng quốc tế Vietcombank (khách hàng cá nhân)*, mẫu 01.ĐKĐK/KHCN, hiệu lực từ 15/04/2026 (trang 23). File: `data/20260415_ DieuLeTheVCB.pdf` (1 tài liệu, `document_id = vcb-credit-card-terms-2026`).
  - Nguồn tải và quyền sử dụng: **[tác giả bổ sung URL/ghi chú giấy phép; chưa có trong repo]**.
  - Quy tắc tính trang: đếm trang PDF vật lý có text layer và nội dung điều khoản; loại bìa, mục lục, trang trống. Kết quả: **23/23 trang có nội dung, không trang trống** (cờ `empty` = không trang nào) ⇒ **23 < 30, chưa đạt yêu cầu tối thiểu của rubric**; cần bổ sung tài liệu (xem phần cải tiến).
- **Chuẩn hóa, lỗi và giới hạn:** (`starter/src/ingestion.py`, PyMuPDF)
  - Làm sạch: Unicode NFC, gộp khoảng trắng, bỏ ký tự ẩn/ligature; xóa header lặp “MẪU 01.ĐKĐK/KHCN” và số trang (23 dòng, nhận diện lặp lại ở đầu/cuối trang, không gắn cứng chuỗi); nối dòng bị ngắt cứng thành một khoản; nối marker đứng riêng một dòng (“1.”, “(i)”, “a)”) với nội dung; nhận diện tiêu đề/khoản và gán `section`, `heading_path` cho từng khối.
  - Kiểm tra bảo toàn: so nội dung chữ-số từng trang giữa Markdown và văn bản đã làm sạch: **đạt 23/23 trang**. Mọi evidence trong benchmark tìm lại được nguyên văn ở đúng trang trong Markdown (20/20).
  - Giới hạn/lỗi: (1) không ghép đoạn qua ranh giới trang (gold chấm theo trang) nên đoạn nối trang chỉ được gắn cờ `continued`; (2) nhận diện tiêu đề dựa heuristic độ dài/dòng kế tiếp, chỉnh theo kiểu ngắt dòng ~105 ký tự của file này; (3) lỗi gốc của PDF được giữ nguyên: “băn bản” (tr.23), “ĐINH” (tr.3), mục 1.21 mang số con 1.20.x (tr.17), tham chiếu “điều 1.16” thực tế là 1.17 (tr.8); (4) dấu chấm sau số mục trong chunk B/C bị bỏ (“1.1.” → “1.1”), không ảnh hưởng evidence; (5) tiêu đề văn bản ở trang 1 có `section` rỗng (nằm trước mục A, không tự đoán); (6) không có OCR, không có bảng thật (`find_tables` báo mỗi trang một bảng nhưng không dùng vì đó là dương tính giả).
- **Embedding, vector store, lệnh chạy, chi phí:**
  - Embedding: `intfloat/multilingual-e5-base`, chạy **local**, lưu ở `models/multilingual-e5-base`, 768 chiều, mean pooling + L2-normalize, tiền tố `passage:` / `query:`, tối đa 512 token (số chunk bị cắt: 0). GPU RTX 3060 (CUDA).
  - Vì env `robot` có `torch 2.5.1+cu121` còn `transformers 5.20.2` yêu cầu `torch >= 2.6` nên không nạp được model; tôi chạy kiến trúc XLM-RoBERTa bằng `torch` + `safetensors` + `tokenizers` (`starter/src/xlmr_encoder.py`), **đối chiếu với bản `transformers` tham chiếu: cosine tối thiểu 1,00000 trên 184 chunk**. Dùng cùng một embedder cho A/B/C; mỗi câu hỏi chỉ embed một lần (vector truy vấn chung cho ba chiến lược).
  - Vector store: PostgreSQL 16.16 + pgvector 0.8.7 (Docker `pgvector/pgvector:0.8.7-pg16`), bảng `chunks` khóa `(strategy, chunk_id)`, cột `vector(768)`, metric **cosine**, tìm **chính xác** (quét tuần tự, không dùng chỉ mục xấp xỉ), `psycopg 3.3.8`, Python 3.10.19. Nạp lại không nhân đôi (đã thử: 206/124/124 không đổi; chunk cũ bị xóa khi nạp tập con).
  - Lệnh: `docker compose -p day6_student_starter up -d --wait`, rồi trong `starter/` với env `robot`: `python -X utf8 -m src.indexing` và `python -X utf8 -m src.run --split all --update-log`.
  - Chi phí: **0 USD** (local, không dùng API trả phí).
- **Metadata bắt buộc, trường lọc, nguồn giá trị và lý do chọn:**
  - Bắt buộc (cả A/B/C): `document_id`, `source`, `page`.
  - Trường lọc bổ sung: `section` ∈ {`A`, `B.I`, `B.II`}, lấy từ tiêu đề cấp lớn của chính văn bản (A. CÁC QUY ĐỊNH CHUNG; B.I QUY ĐỊNH VỀ PHÁT HÀNH VÀ SỬ DỤNG THẺ; B.II CÁC QUY ĐỊNH KHÁC), không tự tạo giá trị. Chỉ ở C còn có `heading_path`, `article` (điều, ví dụ “1.17 Quy định về tra soát, khiếu nại”), `clauses`.
  - Lý do: nhiều con số/cụm lặp lại ở các mục khác nhau (“07 ngày” ở B.I tr.6–7 và B.II tr.22; “30 ngày” ở B.I tr.19 và B.II tr.23; “60 ngày” ở B.I tr.8 và tr.14), nên `section` giúp loại nhiễu. Hạn chế: trang 3 và 20 chứa hai section; filter chỉ so bằng; giá trị filter là **input giả định do người dùng cung cấp trước khi truy xuất**.

## Cấu hình và benchmark
- **A / B / C:**
  - **A – cố định:** cửa sổ 500 ký tự, overlap 50, trên văn bản từng trang đã làm phẳng khoảng trắng; metadata `document_id`, `source`, `page`; không lọc. **206 chunk** (trung bình 471 ký tự).
  - **B – cấu trúc:** gom các khoản nguyên vẹn dưới tiêu đề, tối đa 1000 ký tự; không vượt qua trang, section hay tiêu đề điều; tiêu đề đi cùng nội dung nó dẫn; khoản dài hơn 1000 ký tự tách theo câu; metadata như A; không lọc. **124 chunk** (trung bình 708 ký tự, tối đa 994).
  - **C:** chunk **giống hệt B** (cùng text và id, đã kiểm tra bằng assert); khác biệt **duy nhất** là có thêm metadata `section/heading_path/article/clauses` và **lọc theo `section` chỉ khi câu hỏi có filter** (câu không có filter chạy không lọc).
  - Cùng corpus, cùng model, cosine, top-3. Kích thước A (500/50) theo ví dụ của GUIDE, B (≤1000) chọn thủ công; cả hai được cố định từ lúc thiết kế, **không chỉnh sau khi có kết quả**. Lưu ý A và B khác cả kích thước lẫn cấu trúc.
- **Benchmark ≥20 câu:** `data/benchmark_questions.json`, **20 câu = 15 dev / 5 test**, chia theo chủ đề trước khi chạy (dev: định nghĩa, hạn mức, phí, lãi, sao kê, nhận thẻ, thẻ phụ, từ chối giao dịch, thông báo; test: khiếu nại, nhắc nợ, chấm dứt hợp đồng, giải chấp). Loại câu: 6 trực tiếp, 6 điều kiện, 3 diễn đạt lại, 5 có filter (**3 dev + 2 test**: d12, d13, d14, t01, t04). Câu `d11` có hai trang hợp lệ (tr.12 và tr.5, `alt_gold`).
  - Kiểm chứng evidence: `scripts/verify_benchmark.py` xác nhận từng `evidence_quote` (và `alt_gold`) xuất hiện **nguyên văn** ở trang gold của PDF sau chuẩn hóa: 20/20; kiểm tra số lượng/split/filter và gold của câu filter nằm ở trang thuần của section. Query chỉ là câu hỏi, không chứa gold/đáp án/nguồn.
  - Nguy cơ rò rỉ chủ đề: t03 (khóa thẻ khi trả thiếu tối thiểu) cùng chủ đề rộng với d04, d06; chỉ có một tài liệu nên không chia theo tài liệu.
- **Tiêu chí chọn chiến lược đã chốt trước khi xem test:** **chưa được ghi thành văn bản trước khi chạy test**, nên tôi không khẳng định đã chốt trước. Tiêu chí đang dùng, ghi sau khi có số: ưu tiên Evidence Hit@3, sau đó Hit@1, rồi tuân thủ filter/grounding thủ công, rồi tài nguyên. Những gì đã xảy ra: (i) tham số chunking không đổi sau khi có kết quả; (ii) dev chạy trước, sau đó chạy `--split all`; (iii) khi viết chunking tôi đã đo độ phủ evidence **không qua truy xuất** trên cả 20 câu (A: evidence bị cắt ở d04, d07, t03), và tra chunk chứa gold của t01/t04 để kiểm tra metadata; không chỉnh chiến lược sau đó. Cần tạo test mới nếu muốn kết luận chặt hơn.

## Kết quả
Nguồn số: `starter/results/metrics.md`, `metrics.json`, `ingest_log.json` (chạy 14/11/2026, model `multilingual-e5-base`, cosine, top-3). “Thời gian” = embed toàn bộ chunk (giây, không dùng cache) / nạp vào pgvector; parse + làm sạch PDF một lần: 1,45 s (chung cho cả ba).

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 11/15 | 12/15 | 206 | embed 1,84 s / nạp 0,27 s | 0 USD |
| A | test | 4/5 | 4/5 | 206 | (như trên) | 0 USD |
| B | dev | 14/15 | 15/15 | 124 | embed 1,11 s / nạp 0,18 s | 0 USD |
| B | test | 4/5 | 4/5 | 124 | (như trên) | 0 USD |
| C | dev | 14/15 | 15/15 | 124 | embed 1,30 s / nạp 0,48 s | 0 USD |
| C | test | 4/5 | 4/5 | 124 | (như trên) | 0 USD |

Gộp 20 câu: A 15/20 và 16/20; B 18/20 và 19/20; C 18/20 và 19/20 (Hit@1 và Evidence Hit@3). Độ trễ truy vấn trung bình: A 62 ms, B 53 ms, C 54 ms (một lần chạy, nhiễu lớn).

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | chưa chấm | chưa chấm (kiểm tự động: 15/15 record test có source/page hợp lệ) | N/A (không lọc) | chưa chấm |
| B | chưa chấm | chưa chấm (kiểm tự động: 15/15) | N/A (không lọc) | chưa chấm |
| C | chưa chấm | chưa chấm (kiểm tự động: 15/15, gồm `section` khớp trang) | **2/2 câu test có filter** (5/5 trên cả dev+test) | chưa chấm |

Kiểm tự động metadata chỉ xét `source`, `page` (và `section` ở C) nên luôn đạt; **không thay thế nhãn thủ công**.

Đường dẫn và cách chọn mẫu:
- Trace đầy đủ (top-3 gồm text, score, metadata, cờ hit): `starter/results/traces_A.jsonl`, `traces_B.jsonl`, `traces_C.jsonl`.
- Bảng nhãn thủ công (**chưa điền**): `starter/results/manual_coherence.csv` (34 dòng), `manual_grounding.csv` (15 dòng), `manual_metadata.csv` (45 dòng).
- Mẫu chọn trước khi xem điểm: coherence = 10 vị trí cố định, là khoản ở giữa của các trang 1–10, mọi chiến lược chấm cùng vị trí (có thể có nhiều chunk bao phủ); grounding = 5 câu test × 3 chiến lược; metadata = 5 câu test × top-3 × 3 chiến lược. Người chấm: tác giả (nguy cơ thiên lệch, không dùng LLM judge).

## Phân tích và kết luận
- **So sánh A–B và B–C; 2 ví dụ sai:**
  - **A→B:** trên dev Hit@1 11/15 → 14/15 và Evidence Hit@3 12/15 → 15/15 (+3 câu); trên test không đổi (4/5 và 4/5). Cả 4 câu A trượt đều có **đúng trang** trong top-3 (page-hit 20/20) nhưng không chunk nào chứa trọn evidence: lỗi chunk, không phải lỗi sai trang.
  - **B→C:** Hit@1/Hit@3 **không đổi ở cả 20 câu**. Trên 5 câu filter, lọc làm thay đổi top-3 ở 3 câu (d12, d14, t04) bằng cách loại chunk khác section ở hạng 2–3, nhưng hạng của chunk gold vẫn là 1. Tuân thủ filter: C 5/5; nếu không lọc (B) top-3 chỉ tuân thủ hoàn toàn ở 2/5 câu (d13, t01), còn d12, d14, t04 lẫn chunk ngoài section. Tác dụng của metadata ở đây là **sạch phạm vi**, chưa thể hiện bằng Hit.
  - **Ví dụ sai 1 – d04 (dev, A, gold tr.7):** “Nếu trả hết dư nợ sao kê…” — evidence bị **cắt giữa hai chunk** `A|p07|000` / `A|p07|001` (cửa sổ 500 ký tự cắt giữa khoản 1.5.2.a); top-1 là `A|p07|001` chỉ chứa phần sau (“u chủ thẻ thanh toán toàn bộ…”) nên không đủ evidence (kết quả `page_only`). B giữ nguyên khoản nên hit@1. Tương tự d07 (tr.9, khoản 1.9.1). d11 của A thì khác: evidence nằm trọn trong một chunk nhưng chunk đó không vào top-3 (lỗi xếp hạng).
  - **Ví dụ sai 2 – t03 (test, cả A/B/C, gold tr.15):** hỏi về hai kỳ sao kê liên tiếp trả thiếu tối thiểu. Ở B/C, top-1 là `B|p15|006` (khoản 1.18.3 “Sau Ngày đến hạn thanh toán…”), còn chunk chứa evidence `B|p15|005` (1.18.1–1.18.2) **không có trong top-3**; hạng 2–3 là tr.9 (1.8.2.b.iv) và tr.8. Nguyên nhân: các khoản cùng cụm “không thanh toán đủ số tiền thanh toán tối thiểu” rất giống nhau về từ vựng nên embedding đơn thuần khó phân biệt điều kiện “hai kỳ liên tiếp”; filter `section` không giúp vì các chunk này cùng section B.I.
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:** (tạm thời, vì nhãn thủ công chưa có) chọn **B làm chiến lược nền** (Evidence Hit@3 19/20 so với 16/20 của A, evidence không bị cắt, ít chunk hơn: 124 so với 206, embed nhanh hơn). **C chỉ nên dùng khi người dùng/ngữ cảnh cung cấp sẵn phạm vi (section)**: đảm bảo kết quả đúng phạm vi, chi phí thêm nhỏ (nạp 0,48 s so với 0,18 s), nhưng chưa chứng minh tăng Hit trên mẫu này. Đánh đổi: B tạo chunk dài hơn (trung bình 708 so với 471 ký tự) nên một chunk có thể chứa nhiều ý; A đơn giản nhưng cắt giữa khoản.
- **Hạn chế:**
  - Dữ liệu: 1 tài liệu duy nhất, 23 trang (<30); kết luận chỉ áp dụng trong corpus này.
  - Test chỉ 5 câu: 1 câu = 20 điểm phần trăm; A=B=C ở test đều 4/5 và cùng trượt t03 nên **không phân biệt được** chiến lược trên test. Chỉ 5 câu filter (3 dev, 2 test).
  - A và B khác cả kích thước và cấu trúc nên chênh lệch A–B không tách riêng được tác động của từng yếu tố; Hit tính theo evidence trọn vẹn nên bất lợi cho chunk nhỏ.
  - Nhãn: coherence, grounding, metadata thủ công **chưa chấm**; người chấm sẽ là tác giả (thiên lệch). Metadata tự động là chỉ số tạm, luôn 100%.
  - Thời gian/chi phí: một lần chạy, GPU đã nóng, nhiễu mili-giây; C được embed riêng dù text trùng B (có thể dùng chung vector); chi phí 0 vì local, không phản ánh API.
  - Quy trình: tiêu chí chọn chưa ghi trước khi xem test; đã xem độ phủ evidence trên cả test khi viết chunking (không dùng để chỉnh tham số).
- **Nếu làm lại hoặc mở rộng:**
  1. Bổ sung tài liệu để đủ ≥30 trang (và thêm câu hỏi từ tài liệu mới, có `document_type`/`year` để filter phong phú hơn).
  2. Hoàn thành ba bảng nhãn thủ công và điền lại mục kết quả.
  3. Chạy A với cửa sổ ~1000 ký tự để tách tác động kích thước khỏi cấu trúc; thêm overlap cho B khi tách khoản dài.
  4. Thêm câu filter (hiện chỉ 5) và câu cần “điều kiện/ngoại lệ” như t03; thử hybrid BM25 hoặc reranker, hoặc đưa `heading_path` vào văn bản chunk để cải thiện các khoản gần giống nhau.
  5. Chạy đo thời gian nhiều lần, ghi tách phần chunk/embed/nạp, và ghi tiêu chí chọn chiến lược trước khi chạy test.
