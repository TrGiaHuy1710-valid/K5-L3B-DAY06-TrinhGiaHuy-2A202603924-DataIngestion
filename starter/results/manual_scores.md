# Manual label scores (author-labelled; no LLM judge)

| Strategy | Coherence /2 (positions) | Metadata complete+correct | Filter compliance (auto) | Grounding 0/1/2 | Grounding mean /2 |
|---|---|---|---|---|---|
| A | 0.90/2 (n=10) | 9/15 | N/A (no filter applied) | 0/0/5 | 2.00/2 |
| B | 1.80/2 (n=10) | 9/15 | N/A (no filter applied) | 1/0/4 | 1.60/2 |
| C | 1.80/2 (n=10) | 15/15 | 2/2 (100%) | 1/0/4 | 1.60/2 |

## Coherence detail

| Strategy | per-position mean | mean over all chunks | pessimistic (min per position) | chunks 0/1/2 |
|---|---|---|---|---|
| A | 0.90 | 0.83 | 0.80 | 2/10/0 |
| B | 1.80 | 1.80 | 1.80 | 0/2/8 |
| C | 1.80 | 1.80 | 1.80 | 0/2/8 |

## Coherence < 2

- [A] pos01 vcb-credit-card-terms-2026|A|p01|003 = 1: Khoản 1.5 còn nguyên nhưng chunk mở đầu bằng '...tác liên kết' và kết thúc ở 'Vietcombank phá' (cắt giữa từ); không có tiêu đề mục
- [A] pos02 vcb-credit-card-terms-2026|A|p02|004 = 1: Khoản 1.22 còn nguyên nhưng chunk mở đầu giữa câu của 1.21 ('..., thanh toán hóa đơn') và kết thúc ở 'hợ' (cắt giữa từ)
- [A] pos03 vcb-credit-card-terms-2026|A|p03|004 = 1: Mục 2.3 còn nguyên nhưng chunk bắt đầu giữa từ ('ản sửa đổi...'), trộn danh mục viết tắt với đầu phần B và cắt ở '1.1 ... a. Thẻ được sử'
- [A] pos04 vcb-credit-card-terms-2026|A|p04|003 = 1: Điều 1.2.6 chỉ có câu đầu trọn vẹn; câu thứ hai ('Việc miễn trừ... bất kỳ trách') bị cắt; chunk mở đầu giữa từ 'ưa ra'
- [A] pos05 vcb-credit-card-terms-2026|A|p05|005 = 1: Khoản 1.3.4 a-b còn nguyên nhưng chunk mở đầu giữa câu của khoản f và kết thúc giữa khoản c ('trong trường hợp C')
- [A] pos06 vcb-credit-card-terms-2026|A|p06|003 = 1: Khoản 1.4.15 bắt đầu nguyên vẹn nhưng danh sách các trường hợp bị cắt ở 'số tiền giao dịch thanh toán'; chunk mở đầu bằng mảnh 1.4.14
- [A] pos07 vcb-credit-card-terms-2026|A|p07|003 = 1: Khoản c (tra soát) nguyên vẹn nhưng mất khoản mẹ nên không rõ là lãi của giao dịch nào; chunk mở đầu giữa từ và kết thúc ở '1.6.1 ... a'
- [A] pos08 vcb-credit-card-terms-2026|A|p08|002 = 0: Khoản f (Kỳ sao kê) bị cắt ngay sau 'là khoảng thời gian V' nên định nghĩa của vị trí không còn; chunk còn mở đầu giữa từ
- [A] pos08 vcb-credit-card-terms-2026|A|p08|003 = 1: Khoản f, g, h trọn vẹn nhưng chunk mở đầu bằng mảnh khoản e ('toán đầu tiên.') và kết thúc ở 'trang thông t'
- [A] pos09 vcb-credit-card-terms-2026|A|p09|003 = 1: Khoản (ii) nguyên vẹn nhưng chunk mở đầu giữa từ ('y sao kê'), khoản (i) bị mất đầu, (iii) bị cắt ở 'không đầy'
- [A] pos10 vcb-credit-card-terms-2026|A|p10|003 = 0: Khoản 1.9.6 bị cắt ở 'Khi thực hiện giao dịch tha' nên phần nội dung của vị trí không có trong chunk
- [A] pos10 vcb-credit-card-terms-2026|A|p10|004 = 1: Khoản 1.9.6 nguyên vẹn nhưng chunk mở đầu giữa từ ('c ủy quyền này') và kết thúc giữa 1.9.7
- [B] pos05 vcb-credit-card-terms-2026|B|p05|002 = 1: Chunk mở đầu bằng khoản e, f của mục trước (không có tiêu đề 1.3.3) và 1.3.4 mới có a-b, khoản c (quyền từ chối/thu phí) bị chuyển sang chunk sau
- [B] pos07 vcb-credit-card-terms-2026|B|p07|001 = 1: Khoản (i), (ii), c trọn vẹn nhưng thiếu tiêu đề mục và khoản mẹ nên phạm vi áp dụng của 'c' chỉ suy ra được
- [C] pos05 vcb-credit-card-terms-2026|C|p05|002 = 1: Cùng văn bản với B
- [C] pos07 vcb-credit-card-terms-2026|C|p07|001 = 1: Cùng văn bản với B

## Grounding < 2

- [B] t03 = 0: Top-3 không có khoản 1.18.2 (chunk B|p15|005 không được lấy); chỉ có 1.18.3-1.18.4 (phân loại nợ), phí chậm thanh toán và sao kê, không trả lời được việc khóa thẻ
- [C] t03 = 0: Cùng top-3 với B

## Metadata errors

- [A] t01 rank1 vcb-credit-card-terms-2026|A|p14|000: source/page đúng nhưng thiếu trường section; câu hỏi cần filter section nên không lọc/kiểm được phạm vi
- [A] t01 rank2 vcb-credit-card-terms-2026|A|p15|001: source/page đúng nhưng thiếu trường section; câu hỏi cần filter section nên không lọc/kiểm được phạm vi
- [A] t01 rank3 vcb-credit-card-terms-2026|A|p15|002: source/page đúng nhưng thiếu trường section; câu hỏi cần filter section nên không lọc/kiểm được phạm vi
- [A] t04 rank1 vcb-credit-card-terms-2026|A|p23|005: source/page đúng nhưng thiếu trường section; câu hỏi cần filter section nên không lọc/kiểm được phạm vi
- [A] t04 rank2 vcb-credit-card-terms-2026|A|p17|005: source/page đúng nhưng thiếu trường section; câu hỏi cần filter section nên không lọc/kiểm được phạm vi
- [A] t04 rank3 vcb-credit-card-terms-2026|A|p17|004: source/page đúng nhưng thiếu trường section; câu hỏi cần filter section nên không lọc/kiểm được phạm vi
- [B] t01 rank1 vcb-credit-card-terms-2026|B|p14|000: source/page đúng nhưng thiếu trường section; câu hỏi cần filter section nên không lọc/kiểm được phạm vi
- [B] t01 rank2 vcb-credit-card-terms-2026|B|p15|001: source/page đúng nhưng thiếu trường section; câu hỏi cần filter section nên không lọc/kiểm được phạm vi
- [B] t01 rank3 vcb-credit-card-terms-2026|B|p15|000: source/page đúng nhưng thiếu trường section; câu hỏi cần filter section nên không lọc/kiểm được phạm vi
- [B] t04 rank1 vcb-credit-card-terms-2026|B|p23|004: source/page đúng nhưng thiếu trường section; câu hỏi cần filter section nên không lọc/kiểm được phạm vi
- [B] t04 rank2 vcb-credit-card-terms-2026|B|p17|002: source/page đúng nhưng thiếu trường section; câu hỏi cần filter section nên không lọc/kiểm được phạm vi
- [B] t04 rank3 vcb-credit-card-terms-2026|B|p23|000: source/page đúng nhưng thiếu trường section; câu hỏi cần filter section nên không lọc/kiểm được phạm vi
