# Case Planning v2 — 3 mẫu chạy thật (bằng chứng cho dev log mục 2.4d)

> Khoa chạy `scripts/try_case_plan.py` ngày 2026-09-25/26, lưu nguyên văn tại đây (script không ghi DB).
> Phần "Lỗi quan sát được" và bảng tổng hợp là nhận xét của Khoa.

Provider: groq | model: openai/gpt-oss-120b | temperature: 0.7 | prompt: case_plan_v2

Lưu ý: dòng lệnh hiển thị mất dấu tiếng Việt trong PowerShell (vd "c?m h?c"); cần kiểm tra cột motion trong DB để xác nhận motion có bị hỏng khi truyền vào hay không.
(Ghi chú thêm: 3 mẫu chạy qua script nên KHÔNG có trong DB — xem dev log mục 2.4d, "Motion mất dấu".)

---

## Mẫu 1 — "Nên cấm học sinh sử dụng điện thoại trong trường học" | ai_side = con (Phản đối) | easy

```
python -m scripts.try_case_plan "Nên c?m h?c sinh s? d?ng di?n tho?i trong tru?ng h?c" --ai-side con --difficulty easy
Provider: groq | model: openai/gpt-oss-120b | temperature: 0.7

Lan 1 (4930 ms): OK
```

```json
{
  "motion_interpretation": "Cấm học sinh sử dụng điện thoại trong trường học có nghĩa là không cho phép học sinh mang hoặc bật bất kỳ thiết bị di động nào (smartphone, tablet) vào khuôn viên trường và trong giờ học, trừ những trường hợp đặc biệt được giáo viên cho phép.",
  "definitions": [
    {
      "term": "điện thoại",
      "meaning": "thiết bị di động có khả năng kết nối internet và thực hiện các chức năng liên lạc, tra cứu thông tin và hỗ trợ học tập."
    }
  ],
  "arguments": [
    {
      "id": "A1",
      "title": "Thiết bị điện thoại là công cụ học tập cần thiết",
      "claim": "Cấm điện thoại sẽ làm mất cơ hội học sinh tiếp cận công nghệ và tài nguyên giáo dục ngay tại lớp.",
      "reasoning": "Trong thời đại số, việc sử dụng điện thoại để tra cứu thông tin, truy cập ứng dụng học tập và thực hành kỹ năng số là một phần thiết yếu của quá trình giáo dục; nếu cấm, học sinh sẽ bị hạn chế trong việc rèn luyện năng lực công nghệ cần thiết cho tương lai.",
      "example": "Giả sử một học sinh đang học môn sinh học và muốn xem nhanh video mô phỏng quá trình phân bào; nếu được phép dùng điện thoại, học sinh có thể ngay lập tức mở video, giúp cả lớp hiểu rõ hơn và tiết kiệm thời gian giảng dạy.",
      "impact": "Khi không được sử dụng điện thoại, học sinh sẽ thiếu cơ hội rèn luyện kỹ năng số, giảm khả năng thích nghi với môi trường làm việc hiện đại, và trường học sẽ mất đi một công cụ hỗ trợ giảng dạy hiệu quả."
    },
    {
      "id": "A2",
      "title": "Cấm điện thoại gây khó khăn trong quản lý và tạo ra hành vi vi phạm tiềm ẩn",
      "claim": "Việc cấm điện thoại sẽ làm tăng gánh nặng kiểm soát và dẫn đến việc học sinh giấu điện thoại, gây mất trật tự và căng thẳng cho giáo viên.",
      "reasoning": "Giáo viên không thể giám sát liên tục mọi học sinh; khi quy định cấm, học sinh thường tìm cách che giấu và sử dụng điện thoại trong thời gian không được phép, dẫn đến vi phạm quy tắc và tạo ra môi trường không tin cậy.",
      "example": "Giả sử một học sinh giấu điện thoại trong áo và chỉ sử dụng trong giờ giải lao; khi bị phát hiện, giáo viên phải xử lý kỷ luật, gây xung đột và làm gián đoạn buổi học cho cả lớp.",
      "impact": "Môi trường học tập trở nên căng thẳng, thời gian dạy học bị gián đoạn, giáo viên phải dành công sức cho việc kỷ luật thay vì giảng dạy, và học sinh cảm thấy bị giám sát quá mức, ảnh hưởng tiêu cực đến tinh thần học tập."
    }
  ],
  "anticipated_opponent_arguments": [
    {
      "id": "O1",
      "opponent_claim": "Điện thoại gây mất tập trung, làm giảm kết quả học tập của học sinh.",
      "planned_response": "Chúng tôi thừa nhận có khả năng gây phân tâm, nhưng vấn đề thực chất là thiếu giáo dục về kỷ luật tự giác và quy tắc sử dụng; thay vì cấm hoàn toàn, trường có thể thiết lập thời gian và không gian sử dụng hợp lý, đồng thời đào tạo kỹ năng quản lý thời gian cho học sinh."
    },
    {
      "id": "O2",
      "opponent_claim": "Điện thoại tạo điều kiện cho việc gian lận, bắt nạt qua mạng và tiếp xúc nội dung không phù hợp.",
      "planned_response": "Vấn đề này không phải do thiết bị mà do thiếu giám sát và giáo dục về hành vi trực tuyến; trường có thể áp dụng phần mềm kiểm soát, quy định rõ ràng và chương trình giáo dục về an toàn mạng, thay vì loại bỏ công cụ có lợi cho học tập."
    }
  ],
  "weighing": "Khi cân nhắc tổng thể, lợi ích của việc cho phép học sinh sử dụng điện thoại như một công cụ hỗ trợ học tập, phát triển kỹ năng số và tạo điều kiện cho phương pháp giảng dạy hiện đại vượt trội hơn so với những rủi ro tiềm ẩn. Những rủi ro này có thể được giảm thiểu bằng các chính sách quản lý hợp lý, giáo dục về kỷ luật và an toàn mạng, trong khi việc cấm hoàn toàn sẽ gây mất cơ hội học tập, tăng gánh nặng kiểm soát và tạo môi trường không tin cậy. Do đó, phe phản đối (Opposition) thắng vì lợi ích tổng thể cho giáo dục và xã hội là lớn hơn."
}
```

### Lỗi quan sát được (mẫu 1)
- Phe Phản đối tự định nghĩa motion và thêm ngoại lệ "trừ những trường hợp đặc biệt được giáo viên cho phép" → làm hẹp kiến nghị.
- A1 (ví dụ xem video học tập trên lớp) tấn công đúng trường hợp mà chính motion_interpretation đã miễn trừ → mâu thuẫn nội tại.
- Định nghĩa "điện thoại" đóng khung thiên vị ("hỗ trợ học tập").
- Lọt tiếng Anh trong weighing: "(Opposition)".
- Bối cảnh Việt Nam chung chung.

---

## Mẫu 2 — "Nên bỏ kỳ thi tốt nghiệp THPT" | ai_side = pro (Đề xuất) | medium

```
python -m scripts.try_case_plan "Nên b? k? thi t?t nghi?p THPT" --ai-side pro --difficulty medium
Provider: groq | model: openai/gpt-oss-120b | temperature: 0.7
Case plan lan thu 1 khong hop le: 1 validation error for CaseFile
motion_interpretation
  Field required [type=missing, input_value={'motion_interinterpretat...Việt Nam hiện nay.'}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing

Lan 1 (5335 ms): LOI: 1 validation error for CaseFile
motion_interpretation
  Field required [type=missing, input_value={'motion_interinterpretat...Việt Nam hiện nay.'}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
Raw output:
{
  "motion_interinterpretation":"Bỏ kỳ thi tốt nghiệp THPT có nghĩa là loại bỏ kỳ thi cuối năm trung học phổ thông làm tiêu chuẩn duy nhất để đánh giá học sinh tốt nghiệp, thay thế bằng các hình thức đánh giá liên tục, dự án hoặc đánh giá toàn diện do nhà trường thực hiện.",
  "definitions":[
    {
      "term":"kỳ thi tốt nghiệp THPT",
      "meaning":"Cuộc thi kiểm tra cuối cấp trung học phổ thông, thường là một bài thi viết và thi môn, được dùng để xác nhận học sinh đã hoàn thành chương trình học và làm cơ sở xét tuyển vào đại học."
    }
  ],
  "arguments":[
    {
      "id":"A1",
      "title":"Giảm căng thẳng, bảo vệ sức khỏe tâm thần",
      "claim":"Bỏ kỳ thi tốt nghiệp THPT sẽ giảm đáng kể áp lực và căng thẳng cho học sinh.",
      "reasoning":"Kỳ thi cao điểm tạo ra môi trường cạnh tranh khốc liệt, khiến học sinh phải học nhồi nhét để đạt điểm cao, dẫn tới lo âu, stress và các vấn đề sức khỏe tâm thần. Khi không còn kỳ thi này, học sinh sẽ không phải chịu áp lực chuẩn bị cho một bài kiểm tra quyết định tương lai, từ đó giảm stress và cải thiện sức khỏe tâm thần.",
      "example":"Giả sử một học sinh lớp 12 ở Hà Nội không còn lo lắng về điểm thi cuối năm, thay vào đó cô ấy có thể tập trung vào các dự án thực tế và hoạt động ngoại khóa.",
      "impact":"Sức khỏe tâm thần của hàng triệu học sinh được cải thiện, giảm tỷ lệ bỏ học và các vấn đề liên quan đến stress, đồng thời tạo môi trường học tập lành mạnh hơn cho xã hội."
    },
    {
      "id":"A2",
      "title":"Thúc đẩy giáo dục toàn diện và kỹ năng thực tiễn",
      "claim":"Việc bỏ kỳ thi sẽ khuyến khích các trường áp dụng đánh giá liên tục và dự án, giúp học sinh phát triển kỹ năng toàn diện.",
      "reasoning":"Khi không còn một bài thi quyết định, nhà trường có động lực thiết kế chương trình học dựa trên dự án, thảo luận và đánh giá quá trình, từ đó phát triển tư duy phản biện, sáng tạo và kỹ năng làm việc nhóm – những năng lực cần thiết cho nền kinh tế hiện đại.",
      "example":"Giả sử trườn
[output bị script cắt ngắn tại đây]

Lan 2 (4321 ms): OK
```

```json
{
  "motion_interpretation": "Kiến nghị yêu cầu loại bỏ kỳ thi tốt nghiệp THPT ở Việt Nam, thay thế bằng các hình thức đánh giá khác nhằm đánh giá năng lực học sinh một cách toàn diện hơn.",
  "definitions": [
    {
      "term": "kỳ thi tốt nghiệp THPT",
      "meaning": "Cuộc thi đánh giá cuối cấp 12, là tiêu chuẩn duy nhất để xét tuyển vào đại học."
    }
  ],
  "arguments": [
    {
      "id": "A1",
      "title": "Giảm căng thẳng học sinh",
      "claim": "Bỏ kỳ thi tốt nghiệp THPT sẽ giảm áp lực và cải thiện sức khỏe tâm thần của học sinh.",
      "reasoning": "Kỳ thi tạo ra áp lực cao vì quyết định tương lai; khi không còn kỳ thi, học sinh không phải chịu căng thẳng kéo dài, có thể học tập và sinh hoạt bình thường hơn.",
      "example": "Giả sử một học sinh lớp 12 không phải chuẩn bị cho kỳ thi quyết định tương lai, họ có thể tham gia các hoạt động ngoại khóa và nghỉ ngơi đầy đủ.",
      "impact": "Sức khỏe tâm thần của hàng triệu học sinh được cải thiện, giảm tỷ lệ lo âu, trầm cảm và các vấn đề xã hội liên quan."
    },
    {
      "id": "A2",
      "title": "Thúc đẩy giáo dục toàn diện",
      "claim": "Loại bỏ kỳ thi sẽ khuyến khích các trường trung học tập trung vào giáo dục toàn diện và phát triển kỹ năng thực tế.",
      "reasoning": "Không còn một bài kiểm tra duy nhất, các trường có thể thiết kế chương trình dựa trên dự án, thảo luận và thực hành, giúp học sinh phát triển tư duy phản biện và sáng tạo.",
      "example": "Một trường trung học ở Hà Nội quyết định đánh giá học sinh qua các dự án cộng đồng và bài thuyết trình thay vì điểm thi.",
      "impact": "Học sinh ra trường sẽ có kỹ năng phù hợp với nhu cầu của thị trường lao động hiện đại, nâng cao năng lực cạnh tranh quốc gia."
    },
    {
      "id": "A3",
      "title": "Giảm bất công xã hội",
      "claim": "Bỏ kỳ thi sẽ giảm bất công do chênh lệch điều kiện học tập giữa các gia đình.",
      "reasoning": "Kỳ thi thường lợi cho học sinh có khả năng thuê gia sư hoặc học thêm; khi không còn kỳ thi, đánh giá dựa trên quá trình học chung sẽ giảm lợi thế của gia đình có thu nhập cao.",
      "example": "Giả sử hai học sinh, một đến từ gia đình có khả năng thuê gia sư và một không, nếu không có kỳ thi, họ sẽ được đánh giá qua báo cáo học tập và hoạt động của trường.",
      "impact": "Tăng cơ hội công bằng cho học sinh nghèo, giảm khoảng cách giáo dục và góp phần giảm bất bình xã hội."
    }
  ],
  "anticipated_opponent_arguments": [
    {
      "id": "O1",
      "opponent_claim": "Kỳ thi là tiêu chuẩn khách quan, công bằng để đánh giá năng lực và lựa chọn sinh viên đại học.",
      "planned_response": "Mặc dù kỳ thi mang tính khách quan, nó không phản ánh đầy đủ năng lực thực tiễn; các hệ thống tuyển sinh đa dạng (báo cáo học tập, dự án, phỏng vấn) cũng có thể đạt được công bằng và thậm chí công bằng hơn."
    },
    {
      "id": "O2",
      "opponent_claim": "Việc bỏ kỳ thi sẽ gây hỗn loạn trong quy trình tuyển sinh đại học vì không còn tiêu chí thống nhất.",
      "planned_response": "Có thể xây dựng quy trình tuyển sinh dựa trên đánh giá toàn diện của trường, bao gồm điểm trung bình, danh tiếng trường, và hồ sơ cá nhân; nhiều quốc gia đã áp dụng mô hình này thành công."
    },
    {
      "id": "O3",
      "opponent_claim": "Kỳ thi tạo động lực học tập nghiêm túc cho học sinh, nếu bỏ đi sẽ làm giảm sự nỗ lực.",
      "planned_response": "Động lực có thể được duy trì qua các hình thức học tập dựa dự án, cuộc thi sáng tạo và chương trình thực tập; những hình thức này khuyến khích học sinh học sâu hơn thay vì học để đạt điểm cao."
    }
  ],
  "weighing": "Khi cân nhắc tổng thể, lợi ích về sức khỏe tâm thần, giáo dục toàn diện và giảm bất công xã hội của việc bỏ kỳ thi vượt trội hơn so với các lo ngại về tiêu chuẩn khách quan và quy trình tuyển sinh; các giải pháp thay thế đã được chứng minh khả thi, do đó phe ủng hộ thắng."
}
```

### Lỗi quan sát được (mẫu 2)
- Lần thử 1: model gõ sai tên trường (`motion_interinterpretation`) → validation lỗi, retry thành công ở lần 2.
- Phe Đề xuất lạm dụng quyền định nghĩa: "là tiêu chuẩn duy nhất để xét tuyển vào đại học" — sai thực tế Việt Nam (còn xét học bạ, đánh giá năng lực...) và sai theo hướng có lợi cho phe AI (strawman cài trong định nghĩa).
- Bịa đặt mềm: "nhiều quốc gia đã áp dụng mô hình này thành công" (O2), "các giải pháp thay thế đã được chứng minh khả thi" (weighing).
- Ví dụ A2 không bắt đầu bằng "Giả sử" → đọc như sự kiện có thật ("Một trường trung học ở Hà Nội quyết định...").
- Impact thổi phồng: "giảm tỷ lệ lo âu, trầm cảm".

---

## Mẫu 3 — "Mạng xã hội gây hại nhiều hơn có lợi cho giới trẻ" | ai_side = con (Phản đối) | hard

```
python -m scripts.try_case_plan "M?ng xa h?i gây h?i nhi?u hon có l?i cho gi?i tr?" --ai-side con --difficulty hard
Provider: groq | model: openai/gpt-oss-120b | temperature: 0.7

Lan 1 (4484 ms): OK
```

```json
{
  "motion_interpretation": "Mạng xã hội ở đây được hiểu là các nền tảng trực tuyến cho phép người trẻ tương tác, chia sẻ thông tin và nội dung (ví dụ: Facebook, TikTok, Instagram). Luận đề yêu cầu đánh giá tổng thể tác động của chúng đối với giới trẻ, so sánh mức độ hại và lợi, trong bối cảnh xã hội và giáo dục Việt Nam hiện nay.",
  "definitions": [
    {
      "term": "Mạng xã hội",
      "meaning": "Các nền tảng kỹ thuật số cho phép người dùng tạo hồ sơ, kết nối, chia sẻ nội dung và giao tiếp trực tuyến."
    },
    {
      "term": "Giới trẻ",
      "meaning": "Nhóm người trong độ tuổi từ 15 đến 25, đang trong giai đoạn học tập, đào tạo và bước vào thị trường lao động."
    }
  ],
  "arguments": [
    {
      "id": "A1",
      "title": "Mở rộng cơ hội học tập",
      "claim": "Mạng xã hội mang lại lợi ích giáo dục vượt trội cho giới trẻ.",
      "reasoning": "Các nền tảng cho phép tiếp cận kiến thức miễn phí, hỗ trợ học tập qua video, nhóm thảo luận và chia sẻ tài liệu, giúp học sinh, sinh viên tự học và bổ sung kiến thức ngoài lớp học.",
      "example": "Giả sử một học sinh trung học ở Hà Nội dùng TikTok để xem các video ngắn giải thích các khái niệm toán học khó; nhờ đó cô ấy cải thiện điểm số mà không phải phụ thuộc hoàn toàn vào giáo viên.",
      "impact": "Nâng cao chất lượng học tập và giảm bất bình đẳng giáo dục, đặc biệt cho học sinh ở vùng sâu vùng xa, góp phần xây dựng nguồn nhân lực có tri thức cho đất nước."
    },
    {
      "id": "A2",
      "title": "Gắn kết xã hội và hỗ trợ tinh thần",
      "claim": "Mạng xã hội giúp giới trẻ duy trì kết nối xã hội và giảm cảm giác cô đơn.",
      "reasoning": "Qua việc chia sẻ cảm xúc, tham gia các cộng đồng chung sở thích và nhận hỗ trợ từ bạn bè, người thân, các nền tảng tạo ra môi trường an toàn để trao đổi và tìm kiếm lời khuyên khi gặp khó khăn.",
      "example": "Giả sử một sinh viên năm cuối ở Đà Nẵng cảm thấy áp lực vì tìm việc; anh ấy tham gia nhóm Facebook chuyên về tuyển dụng, nhận được lời khuyên và hỗ trợ từ các thành viên đã có kinh nghiệm, giảm bớt căng thẳng và tăng tự tin.",
      "impact": "Cải thiện sức khỏe tinh thần của giới trẻ, giảm tỷ lệ trầm cảm và tự tử, đồng thời tạo ra mạng lưới hỗ trợ xã hội mạnh mẽ."
    },
    {
      "id": "A3",
      "title": "Thúc đẩy sáng tạo và khởi nghiệp",
      "claim": "Mạng xã hội là nền tảng khởi đầu cho sáng tạo và kinh doanh của giới trẻ.",
      "reasoning": "Các nền tảng cho phép người trẻ trình bày ý tưởng, quảng bá sản phẩm, kết nối với nhà đầu tư tiềm năng và học hỏi từ các doanh nghiệp thành công, từ đó giảm rào cản khởi nghiệp.",
      "example": "Giả sử một sinh viên thiết kế đồ họa ở TP.HCM đăng các tác phẩm của mình lên Instagram; nhờ lượt tương tác, anh được một công ty khởi nghiệp mời hợp tác, biến sở thích thành nguồn thu nhập thực tế.",
      "impact": "Tạo ra cơ hội việc làm và thu nhập cho giới trẻ, kích thích nền kinh tế sáng tạo, đồng thời giảm tỷ lệ thất nghiệp và nạn di cư lao động."
    }
  ],
  "anticipated_opponent_arguments": [
    {
      "id": "O1",
      "opponent_claim": "Mạng xã hội gây ra các vấn đề sức khỏe tinh thần như lo âu, trầm cảm cho giới trẻ.",
      "planned_response": "Nhận diện rằng một số trường hợp cá nhân có thể gặp khó khăn, nhưng nguyên nhân chủ yếu là do việc lạm dụng và thiếu hướng dẫn; với giáo dục kỹ năng số và hỗ trợ tâm lý, lợi ích giáo dục và xã hội của mạng xã hội vẫn vượt trội."
    },
    {
      "id": "O2",
      "opponent_claim": "Mạng xã hội lan truyền thông tin sai lệch và nội dung tiêu cực, ảnh hưởng xấu đến nhận thức của giới trẻ.",
      "planned_response": "Nhấn mạnh rằng vấn đề này không riêng của mạng xã hội mà là vấn đề truyền thông chung; các biện pháp kiểm duyệt, giáo dục nhận thức thông tin và khuyến khích người dùng phản biện sẽ giảm thiểu rủi ro, trong khi các lợi ích truyền kiến thức nhanh chóng vẫn không thể thay thế."
    },
    {
      "id": "O3",
      "opponent_claim": "Mạng xã hội gây nghiện, làm giảm năng suất học tập và công việc của giới trẻ.",
      "planned_response": "Chỉ ra rằng nghiện là hậu quả của việc sử dụng không có kiểm soát, không phải công nghệ; việc thiết lập thời gian sử dụng hợp lý, hỗ trợ từ gia đình và trường học sẽ ngăn chặn hiện tượng này, trong khi các lợi ích học tập và kết nối vẫn mang lại giá trị tổng thể cao hơn."
    }
  ],
  "weighing": "Khi cân nhắc tổng thể, lợi ích giáo dục, sức khỏe tinh thần và cơ hội kinh tế do mạng xã hội mang lại cho giới trẻ vượt trội so với các rủi ro tiềm ẩn. Những rủi ro này chủ yếu xuất phát từ việc sử dụng không có hướng dẫn và có thể được giảm thiểu bằng chính sách giáo dục kỹ năng số, quy định kiểm soát nội dung và hỗ trợ gia đình. Vì vậy, khi xét đến toàn bộ xã hội Việt Nam, mạng xã hội gây hại ít hơn so với lợi ích mà nó đem lại cho giới trẻ."
}
```

### Lỗi quan sát được (mẫu 3)
- Impact thổi phồng, không được reasoning chống đỡ: "giảm tỷ lệ trầm cảm và tự tử" (A2), "giảm tỷ lệ thất nghiệp và nạn di cư lao động" (A3).
- Bối cảnh Việt Nam tốt hơn 2 mẫu trước nhưng phần lớn mang tính bề mặt (chỉ thêm tên thành phố).
- O1 và O3 dùng lặp cùng một chiến lược phản bác ("do lạm dụng / thiếu hướng dẫn").
- Đúng phe, không có số liệu bịa.

---

## Tổng hợp → thay đổi trong case_plan_v3

| Lỗi | Mẫu | Thay đổi v3 |
|---|---|---|
| Định nghĩa thiên vị / strawman | 1, 2 | Quy tắc định nghĩa theo vai (Đề xuất: công bằng, không mô tả sai hiện trạng; Phản đối: chấp nhận cách hiểu phổ biến, không thêm ngoại lệ) |
| Lập luận mâu thuẫn với chính định nghĩa | 1 | Yêu cầu tự kiểm tra nhất quán trước khi trả kết quả |
| Viện dẫn bằng chứng mơ hồ | 2 | Cấm cụm "nghiên cứu cho thấy", "nhiều quốc gia...", "đã được chứng minh"; detect_vague_evidence log lại |
| Ví dụ không có "Giả sử" | 2 | Validator bằng code, vi phạm → retry |
| Impact thổi phồng | 2, 3 | Impact phải tương xứng với reasoning |
| Lọt tiếng Anh | 1 | Chỉ dùng tiếng Việt, kể cả tên phe |
| Gõ sai tên trường JSON | 2 | Bật structured output (JSON schema strict) trên Groq |
