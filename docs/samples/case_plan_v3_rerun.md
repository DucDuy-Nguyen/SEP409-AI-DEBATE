# Case Planning v3 — chạy lại đúng 3 cấu hình của mẫu v2 (2026-09-26)

> Claude chạy `scripts/try_case_plan.py` với cùng motion / phe / độ khó như
> `case_plan_v2_real_runs.md`. Provider: groq | model: openai/gpt-oss-120b | temperature: 0.7 |
> prompt: case_plan_v3 | JSON schema strict: bật. Mỗi cấu hình chạy 1 lần (n=1) — so sánh với v2
> xem dev log mục 2.4d. Output dưới đây là nguyên văn stdout của script.

---

## Mẫu 1 — "Nên cấm học sinh sử dụng điện thoại trong trường học" | ai_side = con (Phản đối) | easy

```
Motion (da nhan): Nên cấm học sinh sử dụng điện thoại trong trường học
Motion (ascii):   'N\xean c\u1ea5m h\u1ecdc sinh s\u1eed d\u1ee5ng \u0111i\u1ec7n tho\u1ea1i trong tr\u01b0\u1eddng h\u1ecdc'
Provider: groq | model: openai/gpt-oss-120b | temperature: 0.7

Lan 1 (4402 ms): OK

===== CASE FILE (case_plan_v3) =====
{
  "motion_interpretation": "Kiến nghị đề xuất cấm hoàn toàn học sinh sử dụng điện thoại di động trong thời gian học và trên khuôn viên trường học, bao gồm cả việc gọi, nhắn tin và truy cập internet.",
  "definitions": [
    {
      "term": "điện thoại di động",
      "meaning": "Thiết bị di động cho phép gọi điện, nhắn tin và truy cập internet, thường được mang theo cá nhân."
    }
  ],
  "arguments": [
    {
      "id": "A1",
      "title": "An toàn và liên lạc khẩn cấp",
      "claim": "Cấm điện thoại sẽ làm giảm khả năng liên lạc khẩn cấp của học sinh, gây nguy hiểm cho an toàn trường học.",
      "reasoning": "Trong các tình huống khẩn cấp, điện thoại là kênh liên lạc nhanh nhất để học sinh gọi bố mẹ, gọi xe cứu thương hoặc báo cáo sự cố cho nhà trường; nếu không được phép dùng, thời gian phản ứng sẽ bị kéo dài và nguy cơ thiệt hại tăng lên.",
      "example": "Giả sử một học sinh bất ngờ ngất xỉu trong giờ học và cần gọi xe cứu thương, nhưng do quy định cấm điện thoại, học sinh không thể gọi ngay, phải chờ người khác mang điện thoại, làm trì hoãn việc cấp cứu.",
      "impact": "Kết quả là tăng nguy cơ tổn thương nghiêm trọng hoặc thậm chí tử vong, làm giảm mức độ an toàn tổng thể của môi trường học đường."
    },
    {
      "id": "A2",
      "title": "Tiềm năng học tập và kỹ năng số",
      "claim": "Cấm điện thoại sẽ hạn chế khả năng học tập và phát triển kỹ năng số của học sinh.",
      "reasoning": "Điện thoại thông minh cung cấp truy cập nhanh vào tài liệu, ứng dụng giáo dục, và công cụ hỗ trợ học tập như từ điển, tính toán, video giảng giải; khi bị cấm, học sinh mất cơ hội khai thác nguồn tài nguyên này, đồng thời không được rèn luyện kỹ năng sử dụng công nghệ trong học tập.",
      "example": "Giả sử giáo viên giao bài tập yêu cầu học sinh tra cứu thông tin mới trên internet trong thời gian ngắn, nhưng do quy định cấm điện thoại, học sinh không thể thực hiện ngay và phải chờ thiết bị của nhà trường, gây mất thời gian và giảm hiệu quả học tập.",
      "impact": "Hậu quả là học sinh thiếu kỹ năng số cần thiết cho thời đại công nghệ, giảm chất lượng học tập và khả năng thích nghi với môi trường làm việc tương lai."
    }
  ],
  "anticipated_opponent_arguments": [
    {
      "id": "O1",
      "learner_claim": "Điện thoại gây mất tập trung, làm giảm chất lượng học tập của học sinh.",
      "planned_response": "Công nhận rằng việc lạm dụng điện thoại có thể gây xao lạc, nhưng thay vì cấm toàn bộ, nhà trường nên thiết lập quy tắc sử dụng hợp lý và giáo dục kỹ năng tự quản lý thời gian, đồng thời áp dụng các biện pháp giám sát trong giờ học."
    },
    {
      "id": "O2",
      "learner_claim": "Điện thoại tạo môi trường bắt nạt qua mạng và ảnh hưởng tiêu cực đến tinh thần học sinh.",
      "planned_response": "Thừa nhận vấn đề bắt nạt qua mạng, nhưng giải pháp hiệu quả hơn là triển khai chương trình giáo dục về an toàn mạng, giám sát nội dung và can thiệp kịp thời, thay vì loại bỏ hoàn toàn công cụ có giá trị giáo dục."
    }
  ],
  "weighing": "Khi cân nhắc tổng thể, việc cấm điện thoại sẽ gây mất an toàn trong các tình huống khẩn cấp và hạn chế lợi ích giáo dục quan trọng, trong khi các vấn đề như mất tập trung hay bắt nạt có thể được giải quyết bằng các quy chế quản lý, giáo dục và giám sát hợp lý; do đó, phe phản đối có lập luận mạnh hơn và thắng trong việc bảo vệ an toàn và phát triển kỹ năng của học sinh."
}

===== BANG CHUNG MO HO =====
(khong phat hien cum nao)
```

---

## Mẫu 2 — "Nên bỏ kỳ thi tốt nghiệp THPT" | ai_side = pro (Đề xuất) | medium

```
Motion (da nhan): Nên bỏ kỳ thi tốt nghiệp THPT
Motion (ascii):   'N\xean b\u1ecf k\u1ef3 thi t\u1ed1t nghi\u1ec7p THPT'
Provider: groq | model: openai/gpt-oss-120b | temperature: 0.7

Lan 1 (5802 ms): OK

===== CASE FILE (case_plan_v3) =====
{
  "motion_interpretation": "Kiến nghị đề nghị loại bỏ kỳ thi tốt nghiệp trung học phổ thông, nghĩa là không tổ chức kỳ thi chung cuối cấp để quyết định việc tốt nghiệp và xét tuyển đại học; giả định rằng hệ thống đánh giá sẽ được thay thế bằng các hình thức đánh giá liên tục và tiêu chuẩn địa phương.",
  "definitions": [
    {
      "term": "kỳ thi tốt nghiệp THPT",
      "meaning": "Kỳ thi cuối cấp lớp 12 được tổ chức trên toàn quốc, dùng để xác định việc tốt nghiệp và là một trong các tiêu chí xét tuyển đại học."
    }
  ],
  "arguments": [
    {
      "id": "A1",
      "title": "Giảm áp lực học sinh",
      "claim": "Bỏ kỳ thi tốt nghiệp THPT sẽ giảm áp lực học sinh đáng kể.",
      "reasoning": "Khi không có một kỳ thi quyết định duy nhất, học sinh không phải học gượng gạo để chuẩn bị cho một ngày thi, do đó giảm stress và cải thiện sức khỏe tinh thần.",
      "example": "Giả sử một trường trung học phổ thông ở Hà Nội không tổ chức kỳ thi tốt nghiệp, học sinh có thể tập trung vào việc học hiểu sâu và tham gia các hoạt động ngoại khóa mà không lo lắng về điểm số một lần duy nhất.",
      "impact": "Học sinh sẽ có môi trường học lành mạnh hơn, giảm tỷ lệ bỏ học và nâng cao chất lượng học tập lâu dài."
    },
    {
      "id": "A2",
      "title": "Đa dạng hoá hình thức đánh giá",
      "claim": "Bỏ kỳ thi tốt nghiệp THPT sẽ thúc đẩy việc sử dụng các hình thức đánh giá đa dạng hơn.",
      "reasoning": "Không còn áp lực của một kỳ thi chung, các trường có thể triển khai đánh giá liên tục, dự án thực tế và các bài kiểm tra năng lực, giúp phản ánh khả năng thực tế của học sinh một cách toàn diện.",
      "example": "Giả sử một trường ở Đà Nẵng triển khai đánh giá dự án công nghệ và các bài kiểm tra thường xuyên thay vì một kỳ thi cuối năm, học sinh được đánh giá qua quá trình học suốt năm.",
      "impact": "Kết quả học sinh sẽ phản ánh năng lực thực tế, giúp học sinh chuẩn bị tốt hơn cho công việc và học đại học."
    },
    {
      "id": "A3",
      "title": "Giảm bất bình đẳng vùng miền",
      "claim": "Bỏ kỳ thi tốt nghiệp THPT sẽ giảm bất bình đẳng giữa các vùng miền trong giáo dục.",
      "reasoning": "Kỳ thi chung thường gây bất lợi cho học sinh ở vùng khó khăn do điều kiện giáo dục kém; nếu không có kỳ thi chung, đánh giá dựa trên tiêu chuẩn địa phương sẽ giảm áp lực so sánh không công bằng.",
      "example": "Giả sử học sinh ở một trường miền núi được đánh giá qua các tiêu chuẩn địa phương, không phải so sánh trực tiếp với học sinh thành thị trong cùng một kỳ thi quốc gia.",
      "impact": "Tăng cơ hội học sinh vùng sâu, vùng xa tiếp cận đại học, giảm khoảng cách giáo dục giữa các khu vực."
    }
  ],
  "anticipated_opponent_arguments": [
    {
      "id": "O1",
      "learner_claim": "Kỳ thi tốt nghiệp THPT là tiêu chuẩn khách quan để đánh giá năng lực học sinh trên toàn quốc, giúp công bằng trong tuyển sinh đại học.",
      "planned_response": "Có thể thay thế bằng các công cụ đánh giá chuẩn hoá như bài kiểm tra năng lực quốc gia hoặc hồ sơ học tập liên tục; những công cụ này vẫn giữ tính khách quan mà không gây áp lực của một kỳ thi duy nhất."
    },
    {
      "id": "O2",
      "learner_claim": "Bỏ kỳ thi sẽ làm giảm tính đồng nhất của bằng cấp, gây khó khăn cho các trường đại học trong việc lựa chọn sinh viên.",
      "planned_response": "Các trường đại học có thể áp dụng tuyển sinh dựa trên hồ sơ học tập, thư giới thiệu và các bài kiểm tra năng lực đặc thù; nhiều quốc gia đã áp dụng mô hình này mà vẫn duy trì tiêu chuẩn tuyển sinh cao."
    },
    {
      "id": "O3",
      "learner_claim": "Việc bỏ kỳ thi sẽ gây ra sự lỏng lẻo trong việc chuẩn bị kiến thức cơ bản, dẫn đến giảm chất lượng giáo dục.",
      "planned_response": "Đánh giá liên tục và dự án học tập có thể đảm bảo học sinh nắm vững kiến thức cơ bản, đồng thời tránh việc giảng dạy chỉ hướng tới điểm số cao trong một kỳ thi duy nhất."
    }
  ],
  "weighing": "Mặc dù kỳ thi hiện tại cung cấp một chuẩn chung, việc bỏ nó sẽ giảm áp lực, tăng công bằng vùng miền và cho phép giáo dục đa dạng hoá phương pháp đánh giá; nhờ đó môi trường học tập trở nên lành mạnh, phản ánh năng lực thực tế của học sinh và phù hợp hơn với nhu cầu phát triển của xã hội Việt Nam."
}

===== BANG CHUNG MO HO =====
"nhiều quốc gia"
```

---

## Mẫu 3 — "Mạng xã hội gây hại nhiều hơn có lợi cho giới trẻ" | ai_side = con (Phản đối) | hard

```
Motion (da nhan): Mạng xã hội gây hại nhiều hơn có lợi cho giới trẻ
Motion (ascii):   'M\u1ea1ng x\xe3 h\u1ed9i g\xe2y h\u1ea1i nhi\u1ec1u h\u01a1n c\xf3 l\u1ee3i cho gi\u1edbi tr\u1ebb'
Provider: groq | model: openai/gpt-oss-120b | temperature: 0.7

Lan 1 (4792 ms): OK

===== CASE FILE (case_plan_v3) =====
{
  "motion_interpretation": "Kiến nghị yêu cầu đánh giá tổng thể tác động của mạng xã hội đối với giới trẻ ở Việt Nam, cân nhắc cả các khía cạnh giáo dục, xã hội và cá nhân, với giả định rằng người trẻ sử dụng mạng xã hội đa dạng (Facebook, TikTok, YouTube, Zalo) như một phần thường xuyên trong sinh hoạt hàng ngày.",
  "definitions": [
    {
      "term": "Mạng xã hội",
      "meaning": "Các nền tảng trực tuyến cho phép người dùng tạo, chia sẻ nội dung và tương tác xã hội qua tin nhắn, bài viết, video, livestream."
    },
    {
      "term": "Giới trẻ",
      "meaning": "Nhóm người từ 15 đến 24 tuổi, đang trong giai đoạn học tập, đào tạo nghề hoặc bước vào đời sống lao động tại Việt Nam."
    }
  ],
  "arguments": [
    {
      "id": "A1",
      "title": "Tiếp cận tri thức và học tập",
      "claim": "Mạng xã hội cung cấp nguồn tài nguyên giáo dục phong phú, giúp giới trẻ học hỏi và nâng cao kỹ năng.",
      "reasoning": "Các nền tảng cho phép chia sẻ video hướng dẫn, tài liệu học tập và các nhóm thảo luận chuyên đề; người trẻ có thể tự học ngoài giờ học chính thống, giảm khoảng cách địa lý và chi phí.",
      "example": "Giả sử một học sinh trung học ở tỉnh miền núi sử dụng YouTube để xem các bài giảng toán mà trường không có giáo viên chuyên môn, nhờ đó cải thiện điểm số và tự tin hơn trong kỳ thi.",
      "impact": "Nhờ tiếp cận kiến thức nhanh chóng, học sinh có khả năng nâng cao thành tích học tập và mở rộng cơ hội nghề nghiệp trong tương lai."
    },
    {
      "id": "A2",
      "title": "Kết nối xã hội và hỗ trợ tinh thần",
      "claim": "Mạng xã hội tạo không gian giao lưu, giúp giới trẻ duy trì và mở rộng các mối quan hệ xã hội, giảm cảm giác cô đơn.",
      "reasoning": "Qua việc nhắn tin, chia sẻ hình ảnh, tham gia các nhóm sở thích, người trẻ có thể giữ liên lạc với bạn bè, người thân và tìm kiếm cộng đồng chia sẻ kinh nghiệm, hỗ trợ khi gặp khó khăn.",
      "example": "Giả sử một sinh viên mới chuyển đến thành phố lớn cảm thấy lạc lõng, nhưng thông qua một nhóm Facebook của sinh viên cùng trường, cô nhận được lời khuyên về chỗ ở, việc làm bán thời gian và bạn bè mới, giúp cô hoà nhập nhanh hơn.",
      "impact": "Mối quan hệ xã hội vững chắc hỗ trợ sức khỏe tinh thần, giảm nguy cơ trầm cảm và tăng khả năng đối mặt với stress trong học tập và công việc."
    },
    {
      "id": "A3",
      "title": "Thúc đẩy tham gia công dân và nhận thức xã hội",
      "claim": "Mạng xã hội là công cụ hiệu quả để giới trẻ nắm bắt thông tin xã hội, tham gia các phong trào cộng đồng và phát triển ý thức công dân.",
      "reasoning": "Các chiến dịch truyền thông, thông tin về bầu cử, môi trường, quyền trẻ em thường được lan truyền nhanh trên mạng xã hội; người trẻ có thể dễ dàng tham gia các hoạt động tình nguyện, biểu tình trực tuyến hoặc chia sẻ quan điểm cá nhân.",
      "example": "Giả sử một nhóm học sinh ở Hà Nội tổ chức chiến dịch thu gom rác trên TikTok, thu hút hàng ngàn lượt chia sẻ, khiến nhiều bạn trẻ khác tham gia và tạo ra một phong trào sạch môi trường tại địa phương.",
      "impact": "Sự tham gia tích cực nâng cao ý thức trách nhiệm xã hội của thế hệ trẻ, góp phần xây dựng cộng đồng bền vững và dân chủ."
    }
  ],
  "anticipated_opponent_arguments": [
    {
      "id": "O1",
      "learner_claim": "Mạng xã hội gây lo âu, trầm cảm và các vấn đề sức khỏe tinh thần cho giới trẻ.",
      "planned_response": "Chỉ ra rằng các vấn đề sức khỏe tinh thần thường xuất phát từ cách sử dụng không kiểm soát; giáo dục kỹ năng sử dụng lành mạnh và giới hạn thời gian sẽ giảm thiểu rủi ro, trong khi lợi ích giáo dục và xã hội vẫn còn đáng kể."
    },
    {
      "id": "O2",
      "learner_claim": "Mạng xã hội lan truyền thông tin sai lệch và nội dung tiêu cực, làm hại nhận thức của giới trẻ.",
      "planned_response": "Nhấn mạnh rằng khả năng kiểm chứng và phản biện thông tin là kỹ năng cần được dạy trong trường học; mạng xã hội cũng cung cấp công cụ báo cáo và lọc nội dung, và người trẻ có thể học cách phân biệt nguồn tin đáng tin."
    },
    {
      "id": "O3",
      "learner_claim": "Mạng xã hội gây nghiện, làm giảm thời gian học tập và làm việc, dẫn đến suy giảm năng suất.",
      "planned_response": "Lập luận rằng nghiện mạng xã hội là vấn đề quản lý thời gian chứ không phải bản chất công cụ; với quy tắc tự kiểm soát và hỗ trợ gia đình, người trẻ có thể cân bằng giữa việc sử dụng mạng xã hội và các hoạt động học tập, còn mạng xã hội còn giúp họ tìm tài liệu học tập nhanh chóng."
    }
  ],
  "weighing": "Khi cân nhắc tổng thể, lợi ích giáo dục, kết nối xã hội và khuyến khích tham gia công dân mà mạng xã hội mang lại cho giới trẻ ở Việt Nam vượt trội hơn các rủi ro tiềm ẩn; những rủi ro này chủ yếu xuất phát từ cách sử dụng không hợp lý và có thể được giảm thiểu bằng giáo dục kỹ năng số và quản lý thời gian, trong khi lợi ích không thể thay thế được bằng các phương tiện truyền thống."
}

===== BANG CHUNG MO HO =====
(khong phat hien cum nao)
```
