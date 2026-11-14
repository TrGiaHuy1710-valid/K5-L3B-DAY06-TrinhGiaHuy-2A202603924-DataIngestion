# Báo cáo cá nhân — Day 6

> **Trạng thái:** phần truy xuất tự động (Hit@1, Evidence Hit@3, filter, chunk, thời gian) đã chạy xong ngày 14/11/2026.

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
| A | **0,90/2** (n = 10 vị trí; 12 chunk) | **9/15** | N/A (không lọc) | **0/0/5**, trung bình **2,00/2** |
| B | **1,80/2** (n = 10 vị trí; 10 chunk) | **9/15** | N/A (không lọc) | **1/0/4**, trung bình **1,60/2** |
| C | **1,80/2** (n = 10 vị trí; 10 chunk) | **15/15** | **2/2 câu test có filter** (5/5 trên cả dev+test) | **1/0/4**, trung bình **1,60/2** |

Cách tính (`starter/src/manual_scores.py`): coherence mỗi vị trí = trung bình nhãn của các chunk phủ vị trí đó, rồi trung bình 10 vị trí /2 (trung bình theo chunk: A 0,83, B 1,80, C 1,80; theo mức thấp nhất mỗi vị trí: A 0,80). Phân bố nhãn coherence theo chunk (0/1/2): A 2/10/0, B 0/2/8, C 0/2/8. Metadata “đủ và đúng” = `source` và `page` đúng với nguồn, và có `section` đúng khi câu hỏi cần filter (t01, t04). A và B bị 0 ở đúng 6 dòng của hai câu filter vì **không có trường `section`**; `source`/`page` đúng ở cả 45/45 dòng. Ở C, mọi `section` khớp block thật trên trang; có 3 ghi chú nhỏ không tính lỗi: chunk `C|p23|000` (tiếp nối từ trang 22) có `clauses` rỗng, `C|p14|000` lặp `1.17.1` hai lần, `C|p15|000` có nhãn `b.` không rõ khoản mẹ.

Nhãn dưới 2 và lý do đầy đủ: `starter/results/manual_scores.md` và các cột `reason` / `error_note` trong ba file CSV. Tóm tắt: **A** toàn bộ chunk là 1 hoặc 0 vì cửa sổ 500 ký tự cắt giữa từ ở hai đầu (pos08 và pos10 có chunk cắt ngay trong khoản của vị trí, nhãn 0); **B/C** mất điểm ở pos05 (mục 1.3.4 bị tách, khoản c nằm chunk sau) và pos07 (thiếu tiêu đề và khoản mẹ). Grounding: B/C trượt t03 (nhãn 0: top-3 không có khoản 1.18.2); A đạt 2 ở t03 chỉ khi **ghép hai chunk liền kề** (evidence tách, có chồng lấn 50 ký tự), nên Evidence Hit@3 tự động tính là trượt còn nhãn grounding là 2.

Kiểm tự động metadata (`source`, `page`, `section` ở C) cho 15/15 ở cả ba chiến lược; nó khác nhãn thủ công ở chỗ không xét việc câu hỏi cần trường nào.

Đường dẫn và cách chọn mẫu:
- Trace đầy đủ (top-3 gồm text, score, metadata, cờ hit): `starter/results/traces_A.jsonl`, `traces_B.jsonl`, `traces_C.jsonl`.
- Bảng nhãn thủ công đã điền: `starter/results/manual_coherence.csv` (32 dòng), `manual_grounding.csv` (15 dòng), `manual_metadata.csv` (45 dòng); tổng hợp ở `manual_scores.md` / `.json`.
- Mẫu chọn: coherence = 10 vị trí cố định, là khoản ở giữa của các trang 1–10 (quy tắc cố định trong code), mọi chiến lược chấm cùng vị trí (có thể có nhiều chunk bao phủ); grounding = 5 câu test × 3 chiến lược; metadata = 5 câu test × top-3 × 3 chiến lược.
- **Người chấm và phương pháp (ghi rõ):** nhãn do **trợ lý AI (Claude)** chấm, đây là một LLM judge **do một mô hình duy nhất thực hiện, không phải tác giả và không có người thứ hai**; chưa có nhãn của người. Quy tắc: coherence 0/1/2 theo GUIDE (2 = ý của vị trí trọn vẹn và tự hiểu; 1 = ý còn nhưng thiếu ngữ cảnh hoặc bị cắt giữa từ/khoản ở rìa; 0 = chính khoản của vị trí bị cắt); grounding chấm trên cả top-3 (2 = đủ trả lời và truy nguồn; 0 = không có evidence); metadata đối chiếu từng dòng với `pages.json`. Nhãn **không mù**: người chấm đã thấy Hit tự động và biết chunk thuộc chiến lược nào; chúng được viết sau khi có kết quả Hit. **Chưa chạy kiểm tra độc lập** (chấm lại bởi tác giả hoặc người thứ hai). Cần tác giả rà soát, nhất là các nhãn 1 của A (chấm khắt khe: cắt giữa từ ở rìa là bị trừ dù khoản vị trí còn nguyên).
- **Sửa lỗi bảng mẫu trong lúc chấm:** hàm tìm chunk phủ vị trí so khớp 40 ký tự đầu của anchor; riêng pos04 chuỗi này trùng với khoản 1.2.1 nên A chọn nhầm chunk (khoản 1.2.1) và B/C có thêm một chunk thừa. Tôi đổi sang so khớp anchor đầy đủ (`evaluation.py`) và tạo lại bảng coherence trước khi chấm: **34 → 32 dòng**; vị trí mẫu không đổi, chưa có điểm nào bị đổi theo kết quả.

## Phân tích và kết luận
- **So sánh A–B và B–C; 2 ví dụ sai:**
  - **A→B:** trên dev Hit@1 11/15 → 14/15 và Evidence Hit@3 12/15 → 15/15 (+3 câu); trên test không đổi (4/5 và 4/5). Cả 4 câu A trượt đều có **đúng trang** trong top-3 (page-hit 20/20) nhưng không chunk nào chứa trọn evidence: lỗi chunk, không phải lỗi sai trang.
  - **B→C:** Hit@1/Hit@3 **không đổi ở cả 20 câu**. Trên 5 câu filter, lọc làm thay đổi top-3 ở 3 câu (d12, d14, t04) bằng cách loại chunk khác section ở hạng 2–3, nhưng hạng của chunk gold vẫn là 1. Tuân thủ filter: C 5/5; nếu không lọc (B) top-3 chỉ tuân thủ hoàn toàn ở 2/5 câu (d13, t01), còn d12, d14, t04 lẫn chunk ngoài section. Tác dụng của metadata ở đây là **sạch phạm vi**, chưa thể hiện bằng Hit.
  - **Coherence, metadata, grounding (nhãn do AI chấm, xem giới hạn):** coherence A 0,90/2 → B 1,80/2 (khoảng cách 0,9 điểm, lớn nhất trong năm khía cạnh; nguyên nhân là cửa sổ cố định cắt giữa từ), B = C = 1,80 vì **văn bản chunk giống hệt nhau** (metadata không thuộc văn bản nên không đổi coherence). Metadata đủ và đúng A 9/15, B 9/15 → C 15/15: lợi ích của C nằm ở trường `section` mà A/B không có (6/6 dòng của hai câu filter), không ở tăng Hit. Grounding A 2,00/2 cao hơn B/C 1,60/2 **trái chiều với Hit**: lý do là A đạt t03 nhờ ghép hai chunk liền kề có overlap (B/C không lấy được khoản 1.18.2 nên nhãn 0). Một câu quyết định 0,4 điểm trung bình nên không kết luận A tốt hơn về grounding; chỉ có thể nói ba chiến lược như nhau ở 4/5 câu.
  - **Ví dụ sai 1 – d04 (dev, A, gold tr.7):** “Nếu trả hết dư nợ sao kê…” — evidence bị **cắt giữa hai chunk** `A|p07|000` / `A|p07|001` (cửa sổ 500 ký tự cắt giữa khoản 1.5.2.a); top-1 là `A|p07|001` chỉ chứa phần sau (“u chủ thẻ thanh toán toàn bộ…”) nên không đủ evidence (kết quả `page_only`). B giữ nguyên khoản nên hit@1. Tương tự d07 (tr.9, khoản 1.9.1). d11 của A thì khác: evidence nằm trọn trong một chunk nhưng chunk đó không vào top-3 (lỗi xếp hạng).
  - **Ví dụ sai 2 – t03 (test, cả A/B/C, gold tr.15):** hỏi về hai kỳ sao kê liên tiếp trả thiếu tối thiểu. Ở B/C, top-1 là `B|p15|006` (khoản 1.18.3 “Sau Ngày đến hạn thanh toán…”), còn chunk chứa evidence `B|p15|005` (1.18.1–1.18.2) **không có trong top-3**; hạng 2–3 là tr.9 (1.8.2.b.iv) và tr.8. Nguyên nhân: các khoản cùng cụm “không thanh toán đủ số tiền thanh toán tối thiểu” rất giống nhau về từ vựng nên embedding đơn thuần khó phân biệt điều kiện “hai kỳ liên tiếp”; filter `section` không giúp vì các chunk này cùng section B.I.
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:** (vẫn tạm thời vì nhãn do AI chấm và chưa có người rà soát) chọn **B làm chiến lược nền** (Evidence Hit@3 19/20 so với 16/20 của A, coherence 1,80 so với 0,90, evidence không bị cắt, ít chunk hơn: 124 so với 206, embed nhanh hơn). Grounding không làm đổi lựa chọn vì A cao hơn chỉ nhờ một câu (t03). **C chỉ nên dùng khi người dùng/ngữ cảnh cung cấp sẵn phạm vi (section)**: đảm bảo kết quả đúng phạm vi (filter 5/5, metadata 15/15 so với 9/15), chi phí thêm nhỏ (nạp 0,48 s so với 0,18 s), nhưng chưa chứng minh tăng Hit trên mẫu này. Đánh đổi: B tạo chunk dài hơn (trung bình 708 so với 471 ký tự) nên một chunk có thể chứa nhiều ý; A đơn giản nhưng cắt giữa khoản.
- **Hạn chế:**
  - Dữ liệu: 1 tài liệu duy nhất, 23 trang (<30); kết luận chỉ áp dụng trong corpus này.
  - Test chỉ 5 câu: 1 câu = 20 điểm phần trăm; A=B=C ở test đều 4/5 và cùng trượt t03 nên **không phân biệt được** chiến lược trên test. Chỉ 5 câu filter (3 dev, 2 test).
  - A và B khác cả kích thước và cấu trúc nên chênh lệch A–B không tách riêng được tác động của từng yếu tố; Hit tính theo evidence trọn vẹn nên bất lợi cho chunk nhỏ.
  - Nhãn: coherence, grounding, metadata do **một LLM chấm, không phải người**, không mù, không có người chấm thứ hai nên chưa đo được độ đồng thuận; mẫu coherence chỉ 10 vị trí đều ở 10 trang đầu (tài liệu định nghĩa, ít đại diện cho các điều khoản phía sau), grounding chỉ 5 câu. Điểm metadata của A/B phụ thuộc quy tắc “cần `section` khi có filter” do tôi đặt; nếu chỉ xét `source`/`page` thì cả ba đều 15/15.
  - Thời gian/chi phí: một lần chạy, GPU đã nóng, nhiễu mili-giây; C được embed riêng dù text trùng B (có thể dùng chung vector); chi phí 0 vì local, không phản ánh API.
  - Quy trình: tiêu chí chọn chưa ghi trước khi xem test; đã xem độ phủ evidence trên cả test khi viết chunking (không dùng để chỉnh tham số).
- **Nếu làm lại hoặc mở rộng:**
  1. Bổ sung tài liệu để đủ ≥30 trang (và thêm câu hỏi từ tài liệu mới, có `document_type`/`year` để filter phong phú hơn).
  2. Tác giả (hoặc người thứ hai) chấm lại ba bảng nhãn một cách mù (ẩn tên chiến lược), so với nhãn AI, và đo độ đồng thuận; lấy mẫu coherence rải đều toàn tài liệu thay vì 10 trang đầu.
  3. Chạy A với cửa sổ ~1000 ký tự để tách tác động kích thước khỏi cấu trúc; thêm overlap cho B khi tách khoản dài.
  4. Thêm câu filter (hiện chỉ 5) và câu cần “điều kiện/ngoại lệ” như t03; thử hybrid BM25 hoặc reranker, hoặc đưa `heading_path` vào văn bản chunk để cải thiện các khoản gần giống nhau.
  5. Chạy đo thời gian nhiều lần, ghi tách phần chunk/embed/nạp, và ghi tiêu chí chọn chiến lược trước khi chạy test.
