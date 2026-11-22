/*
  Topic categories: every topic belongs to one of 3 fixed categories, stored as its code (see
  SystemService.BLL/Common/Debate/TopicCategories.cs). Each has a fact base, so every session gets the evidence check.
  There is no catch-all "General" category any more.

    education  Giáo dục
    technology Công nghệ
    society    Xã hội     (no fact yet)

  1. Converts existing categories to a code: a Vietnamese label or English capitals of the 3, and the former categories
     (economy, health, law, culture, philosophy and their labels) moved into society, except the topics named below.
  2. Adds topics per category (skipped when a topic with the same title exists): safe to run again.
  3. Lists the topics still outside the 3 categories ("General", "Chung", ...): give them a category in the admin page.

  Run: sqlcmd -S localhost -E -C -f 65001 -d DebatePracticePlatformDB -i Scripts/SQL/TopicCategories-Seed.sql
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRANSACTION;

-- 1a. Former-category topics that fit technology or education better
UPDATE Topics SET Category = m.Code, UpdatedAt = SYSUTCDATETIME()
FROM Topics t
JOIN (VALUES
    (N'khám sức khỏe tâm thần trong trường học', N'education'),
    (N'camera giám sát nơi công cộng', N'technology'),
    (N'quyền được lãng quên', N'technology'),
    (N'nghệ thuật do ai tạo ra', N'technology')
) AS m(Title, Code) ON LOWER(t.Title) = m.Title
WHERE t.Category <> m.Code;

-- 1b. Existing categories -> codes
UPDATE Topics SET Category = m.Code, UpdatedAt = SYSUTCDATETIME()
FROM Topics t
JOIN (VALUES
    (N'education', N'education'), (N'giáo dục', N'education'),
    (N'technology', N'technology'), (N'công nghệ', N'technology'),
    (N'society', N'society'), (N'xã hội', N'society'),
    (N'economy', N'society'), (N'kinh tế', N'society'),
    (N'health', N'society'), (N'y tế & sức khỏe', N'society'), (N'y tế', N'society'),
    (N'law', N'society'), (N'pháp luật', N'society'),
    (N'culture', N'society'), (N'nghệ thuật & văn hóa', N'society'), (N'văn hóa', N'society'),
    (N'philosophy', N'society'), (N'triết học', N'society')
) AS m(Label, Code) ON LOWER(LTRIM(RTRIM(t.Category))) = m.Label
WHERE t.Category <> m.Code;

-- 2. The topic set (Title, motion debated = Description, Category, Difficulty)
INSERT INTO Topics (Title, Description, Category, Difficulty, CreatedBy, IsActive, CreatedAt)
SELECT s.Title, s.Description, s.Category, s.Difficulty, NULL, 1, SYSUTCDATETIME()
FROM (VALUES
    -- Giáo dục
    (N'Cấm điện thoại trong trường học', N'Nên cấm học sinh sử dụng điện thoại trong trường học.', N'education', N'Easy'),
    (N'Bỏ bài tập về nhà ở tiểu học', N'Nên bỏ bài tập về nhà đối với học sinh tiểu học.', N'education', N'Easy'),
    (N'Học trực tuyến thay lớp học truyền thống', N'Học trực tuyến có thể thay thế hoàn toàn lớp học truyền thống.', N'education', N'Medium'),
    (N'Dùng ChatGPT trong học tập', N'Học sinh nên được phép dùng ChatGPT để hỗ trợ làm bài tập.', N'education', N'Medium'),
    (N'Khám sức khỏe tâm thần trong trường học', N'Trường học nên tổ chức khám sức khỏe tâm thần định kỳ cho học sinh.', N'education', N'Medium'),
    -- Công nghệ
    (N'Kiểm soát AI bằng luật pháp quốc tế', N'Trí tuệ nhân tạo (AI) nên được kiểm soát chặt chẽ bởi luật pháp quốc tế.', N'technology', N'Hard'),
    (N'AI và thị trường lao động', N'Trí tuệ nhân tạo gây hại cho thị trường lao động nhiều hơn là mang lại lợi ích.', N'technology', N'Medium'),
    (N'Mạng xã hội và giới trẻ', N'Mạng xã hội gây hại cho giới trẻ nhiều hơn là mang lại lợi ích.', N'technology', N'Easy'),
    (N'Cấm công nghệ deepfake', N'Nên cấm hoàn toàn việc tạo và phát tán nội dung deepfake.', N'technology', N'Hard'),
    (N'Camera giám sát nơi công cộng', N'Lợi ích của camera giám sát nơi công cộng lớn hơn nguy cơ xâm phạm quyền riêng tư.', N'technology', N'Medium'),
    (N'Quyền được lãng quên', N'Mọi người có quyền yêu cầu xóa thông tin cá nhân của mình trên internet.', N'technology', N'Medium'),
    (N'Nghệ thuật do AI tạo ra', N'Tác phẩm do AI tạo ra không nên được công nhận là nghệ thuật.', N'technology', N'Medium'),
    -- Xã hội (gồm kinh tế, y tế, pháp luật, văn hóa, triết học)
    (N'Tuần làm việc 4 ngày', N'Nên áp dụng tuần làm việc 4 ngày cho người lao động.', N'society', N'Medium'),
    (N'Trách nhiệm của người nổi tiếng', N'Người nổi tiếng phải chịu trách nhiệm về ảnh hưởng của mình đối với giới trẻ.', N'society', N'Easy'),
    (N'Nghĩa vụ tình nguyện cho thanh niên', N'Thanh niên nên tham gia nghĩa vụ tình nguyện bắt buộc.', N'society', N'Medium'),
    (N'Thuế đồ uống có đường', N'Nên đánh thuế cao đối với đồ uống có đường.', N'society', N'Medium'),
    (N'Thu nhập cơ bản phổ quát', N'Nhà nước nên chi trả thu nhập cơ bản cho mọi công dân.', N'society', N'Hard'),
    (N'Mua trước trả sau', N'Hình thức mua trước trả sau gây hại cho người tiêu dùng trẻ.', N'society', N'Easy'),
    (N'Cấm thuốc lá điện tử', N'Nên cấm hoàn toàn thuốc lá điện tử.', N'society', N'Easy'),
    (N'Hiến tạng mặc định', N'Mọi công dân nên được mặc định là người hiến tạng, trừ khi đăng ký từ chối.', N'society', N'Hard'),
    (N'Hạ tuổi chịu trách nhiệm hình sự', N'Nên hạ tuổi chịu trách nhiệm hình sự xuống 12 tuổi.', N'society', N'Hard'),
    (N'Bảo tồn lễ hội truyền thống', N'Nhà nước nên tài trợ để duy trì các lễ hội truyền thống.', N'society', N'Easy'),
    (N'Hoàn trả cổ vật', N'Các bảo tàng nên trả lại cổ vật cho quốc gia gốc.', N'society', N'Hard'),
    (N'Tự do và an ninh', N'Hy sinh một phần tự do cá nhân để đổi lấy an ninh là chính đáng.', N'society', N'Hard'),
    (N'Nói dối vì thiện ý', N'Nói dối vì thiện ý là chấp nhận được.', N'society', N'Easy'),
    (N'Hạnh phúc và thành công', N'Hạnh phúc quan trọng hơn thành công.', N'society', N'Easy')
) AS s(Title, Description, Category, Difficulty)
WHERE NOT EXISTS (SELECT 1 FROM Topics t WHERE LOWER(t.Title) = LOWER(s.Title));

COMMIT TRANSACTION;

-- 3. Result
SELECT Category, COUNT(*) AS Topics FROM Topics GROUP BY Category ORDER BY Category;
SELECT TopicId, Title, Category AS CategoryToFix FROM Topics
WHERE Category IS NULL OR Category NOT IN (N'education', N'technology', N'society');
