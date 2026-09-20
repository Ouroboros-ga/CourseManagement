-- ===============================================
-- 查课管理系统 - 数据库初始化脚本
-- 版本：V1.0
-- 日期：2026-09-20
-- 数据库：MySQL 8.0+
-- 字符集：utf8mb4
-- ===============================================

-- 创建数据库
CREATE DATABASE IF NOT EXISTS course_management 
DEFAULT CHARACTER SET utf8mb4 
COLLATE utf8mb4_unicode_ci;

USE course_management;

-- ===============================================
-- 1. 用户表
-- ===============================================
DROP TABLE IF EXISTS `user`;
CREATE TABLE `user` (
  `id` BIGINT(20) NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  `username` VARCHAR(50) NOT NULL COMMENT '用户名（学号/工号）',
  `password` VARCHAR(100) NOT NULL COMMENT '密码（加密存储）',
  `nickname` VARCHAR(50) DEFAULT NULL COMMENT '昵称',
  `avatar` VARCHAR(255) DEFAULT NULL COMMENT '头像 URL',
  `phone` VARCHAR(20) DEFAULT NULL COMMENT '手机号',
  `email` VARCHAR(100) DEFAULT NULL COMMENT '邮箱',
  `openid` VARCHAR(64) DEFAULT NULL COMMENT '微信 OpenID',
  `union_id` VARCHAR(64) DEFAULT NULL COMMENT '微信 UnionID',
  `role` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '角色：0-学生，1-教师，2-管理员',
  `major_id` BIGINT(20) DEFAULT NULL COMMENT '所属专业 ID（学生用）',
  `class_id` BIGINT(20) DEFAULT NULL COMMENT '所属班级 ID（学生用）',
  `department` VARCHAR(100) DEFAULT NULL COMMENT '所属院系（教师用）',
  `status` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '状态：0-禁用，1-正常',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_username` (`username`),
  UNIQUE KEY `uk_openid` (`openid`),
  KEY `idx_role` (`role`),
  KEY `idx_major_id` (`major_id`),
  KEY `idx_class_id` (`class_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表';

-- ===============================================
-- 2. 专业表
-- ===============================================
DROP TABLE IF EXISTS `major`;
CREATE TABLE `major` (
  `id` BIGINT(20) NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  `name` VARCHAR(100) NOT NULL COMMENT '专业名称',
  `code` VARCHAR(20) NOT NULL COMMENT '专业代码',
  `department` VARCHAR(100) NOT NULL COMMENT '所属院系',
  `description` TEXT DEFAULT NULL COMMENT '专业描述',
  `status` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '状态：0-禁用，1-正常',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_code` (`code`),
  KEY `idx_department` (`department`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='专业表';

-- ===============================================
-- 3. 班级表
-- ===============================================
DROP TABLE IF EXISTS `class`;
CREATE TABLE `class` (
  `id` BIGINT(20) NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  `name` VARCHAR(50) NOT NULL COMMENT '班级名称',
  `code` VARCHAR(20) NOT NULL COMMENT '班级编码',
  `major_id` BIGINT(20) NOT NULL COMMENT '所属专业 ID',
  `grade` INT(4) NOT NULL COMMENT '年级（如：2024）',
  `year` TINYINT(2) NOT NULL COMMENT '年级（如：1 表示大一）',
  `advisor` VARCHAR(50) DEFAULT NULL COMMENT '班主任/辅导员',
  `student_count` INT(6) NOT NULL DEFAULT 0 COMMENT '学生人数',
  `status` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '状态：0-禁用，1-正常',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_code` (`code`),
  KEY `idx_major_id` (`major_id`),
  KEY `idx_grade_year` (`grade`, `year`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='班级表';

-- ===============================================
-- 4. 课程表
-- ===============================================
DROP TABLE IF EXISTS `course`;
CREATE TABLE `course` (
  `id` BIGINT(20) NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  `name` VARCHAR(100) NOT NULL COMMENT '课程名称',
  `code` VARCHAR(50) NOT NULL COMMENT '课程编号/课号',
  `credit` DECIMAL(3,1) NOT NULL COMMENT '学分',
  `hours` INT(4) NOT NULL COMMENT '总课时',
  `type` VARCHAR(20) DEFAULT '必修' COMMENT '课程类型：必修/选修/通识',
  `major_id` BIGINT(20) DEFAULT NULL COMMENT '适用专业 ID',
  `teacher_id` BIGINT(20) DEFAULT NULL COMMENT '主讲教师 ID',
  `description` TEXT DEFAULT NULL COMMENT '课程描述',
  `prerequisite` VARCHAR(255) DEFAULT NULL COMMENT '先修课程',
  `status` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '状态：0-禁用，1-正常',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_code` (`code`),
  KEY `idx_major_id` (`major_id`),
  KEY `idx_teacher_id` (`teacher_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='课程表';

-- ===============================================
-- 5. 教室表
-- ===============================================
DROP TABLE IF EXISTS `room`;
CREATE TABLE `room` (
  `id` BIGINT(20) NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  `name` VARCHAR(50) NOT NULL COMMENT '教室名称',
  `building` VARCHAR(50) NOT NULL COMMENT '所在楼栋',
  `floor` INT(2) DEFAULT NULL COMMENT '楼层',
  `capacity` INT(4) DEFAULT NULL COMMENT '座位数',
  `type` VARCHAR(20) DEFAULT '普通教室' COMMENT '教室类型：普通教室/机房/实验室',
  `equipment` VARCHAR(255) DEFAULT NULL COMMENT '设备配置（逗号分隔）',
  `status` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '状态：0-禁用，1-可用',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_building` (`building`),
  KEY `idx_type` (`type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='教室表';

-- ===============================================
-- 6. 课表表
-- ===============================================
DROP TABLE IF EXISTS `schedule`;
CREATE TABLE `schedule` (
  `id` BIGINT(20) NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  `course_id` BIGINT(20) NOT NULL COMMENT '课程 ID',
  `user_id` BIGINT(20) NOT NULL COMMENT '用户 ID',
  `class_id` BIGINT(20) DEFAULT NULL COMMENT '班级 ID',
  `room_id` BIGINT(20) NOT NULL COMMENT '教室 ID',
  `week_start` INT(2) NOT NULL COMMENT '周次开始（1-18）',
  `week_end` INT(2) NOT NULL COMMENT '周次结束（1-18）',
  `day_of_week` TINYINT(1) NOT NULL COMMENT '星期几（1-7，1 为周一）',
  `start_time` TIME NOT NULL COMMENT '开始时间',
  `end_time` TIME NOT NULL COMMENT '结束时间',
  `weeks` VARCHAR(50) DEFAULT NULL COMMENT '具体周数（如：1-10,12-18）',
  `semester` VARCHAR(20) NOT NULL COMMENT '学期（如：2024-2025 上学期）',
  `academic_year` VARCHAR(9) NOT NULL COMMENT '学年（如：2024-2025）',
  `is_deleted` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '删除标记：0-未删除，1-已删除',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_course_id` (`course_id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_class_id` (`class_id`),
  KEY `idx_room_id` (`room_id`),
  KEY `idx_day_time` (`day_of_week`, `start_time`),
  KEY `idx_semester` (`semester`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='课表表';

-- ===============================================
-- 7. 成绩表
-- ===============================================
DROP TABLE IF EXISTS `grade`;
CREATE TABLE `grade` (
  `id` BIGINT(20) NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  `user_id` BIGINT(20) NOT NULL COMMENT '学生 ID',
  `course_id` BIGINT(20) NOT NULL COMMENT '课程 ID',
  `schedule_id` BIGINT(20) DEFAULT NULL COMMENT '课表 ID',
  `score` DECIMAL(4,1) DEFAULT NULL COMMENT '成绩（0-100）',
  `grade_level` VARCHAR(2) DEFAULT NULL COMMENT '等级（A/B/C/D/E）',
  `exam_type` VARCHAR(20) DEFAULT '期末' COMMENT '考试类型：平时/期中/期末/其他',
  `remark` VARCHAR(255) DEFAULT NULL COMMENT '备注',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_course` (`user_id`, `course_id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_course_id` (`course_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='成绩表';

-- ===============================================
-- 8. 选课记录表
-- ===============================================
DROP TABLE IF EXISTS `course_user`;
CREATE TABLE `course_user` (
  `id` BIGINT(20) NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  `user_id` BIGINT(20) NOT NULL COMMENT '用户 ID',
  `course_id` BIGINT(20) NOT NULL COMMENT '课程 ID',
  `semester` VARCHAR(20) NOT NULL COMMENT '学期',
  `status` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '状态：0-退课，1-正常，2-已毕业',
  `added_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '添加时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_course` (`user_id`, `course_id`, `semester`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_course_id` (`course_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='选课记录表';

-- ===============================================
-- 9. 操作日志表
-- ===============================================
DROP TABLE IF EXISTS `operation_log`;
CREATE TABLE `operation_log` (
  `id` BIGINT(20) NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  `user_id` BIGINT(20) DEFAULT NULL COMMENT '操作用户 ID',
  `action` VARCHAR(50) NOT NULL COMMENT '操作类型（查询/新增/修改/删除）',
  `module` VARCHAR(50) NOT NULL COMMENT '模块名称',
  `content` TEXT DEFAULT NULL COMMENT '操作内容 JSON',
  `ip` VARCHAR(50) DEFAULT NULL COMMENT 'IP 地址',
  `user_agent` VARCHAR(500) DEFAULT NULL COMMENT '用户代理',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_action` (`action`),
  KEY `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='操作日志表';

-- ===============================================
-- 初始化数据
-- ===============================================

-- 插入默认管理员账号（密码：admin123，实际应加密）
INSERT INTO `user` (`username`, `password`, `nickname`, `role`, `status`) VALUES
('admin', '$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZgENzVF7QrY5pGq7lWWxvFJhKjYKG', '系统管理员', 2, 1);

-- 插入示例专业数据
INSERT INTO `major` (`name`, `code`, `department`, `description`) VALUES
('计算机科学与技术', 'CS001', '信息工程学院', '培养具备计算机科学与技术基本理论和技术的应用型人才'),
('软件工程', 'SE002', '信息工程学院', '培养具备软件工程设计、开发、管理能力的高级专门人才'),
('数据科学与大数据技术', 'DS003', '信息工程学院', '培养掌握大数据处理与分析技术的专业人才');

-- 插入示例班级数据
INSERT INTO `class` (`name`, `code`, `major_id`, `grade`, `year`, `student_count`) VALUES
('计算机 1 班', 'CS2024001', 1, 2024, 1, 45),
('计算机 2 班', 'CS2024002', 1, 2024, 1, 42),
('软件工程 1 班', 'SE2024001', 2, 2024, 1, 48);

-- 插入示例教室数据
INSERT INTO `room` (`name`, `building`, `floor`, `capacity`, `type`, `equipment`) VALUES
('A101', 'A 栋', 1, 50, '普通教室', '投影仪、空调'),
('A102', 'A 栋', 1, 50, '普通教室', '投影仪、空调'),
('B201', 'B 栋', 2, 60, '机房', '计算机 60 台、多媒体设备'),
('C301', 'C 栋', 3, 40, '实验室', '实验设备、投影仪');

-- 插入示例课程数据
INSERT INTO `course` (`name`, `code`, `credit`, `hours`, `type`, `major_id`, `description`) VALUES
('Java 程序设计', 'CS101', 4.0, 64, '必修', 1, '学习 Java 编程语言基础'),
('数据结构', 'CS102', 4.0, 64, '必修', 1, '学习常见数据结构与算法'),
('操作系统', 'CS103', 3.0, 48, '必修', 1, '学习操作系统原理与应用'),
('软件工程导论', 'SE101', 3.0, 48, '必修', 2, '软件工程基本概念与方法'),
('高等数学', 'GS101', 5.0, 96, '通识', NULL, '大学数学基础课程');

-- 插入示例课表数据（第一学期）
INSERT INTO `schedule` (`course_id`, `user_id`, `class_id`, `room_id`, `week_start`, `week_end`, `day_of_week`, `start_time`, `end_time`, `weeks`, `semester`, `academic_year`) VALUES
(1, 1, 1, 1, 1, 18, 1, '08:00:00', '09:35:00', '1-10,12-18', '2024-2025 上学期', '2024-2025'),
(1, 2, 1, 1, 1, 18, 3, '10:00:00', '11:35:00', '1-10,12-18', '2024-2025 上学期', '2024-2025'),
(2, 1, 1, 2, 1, 18, 2, '14:00:00', '15:35:00', '1-10,12-18', '2024-2025 上学期', '2024-2025'),
(3, 1, 1, 3, 1, 18, 4, '08:00:00', '09:35:00', '1-10,12-18', '2024-2025 上学期', '2024-2025');

-- ===============================================
-- 视图创建（可选）
-- ===============================================

-- 学生课表视图
CREATE OR REPLACE VIEW student_schedule AS
SELECT 
    u.id AS user_id,
    u.username,
    u.nickname,
    c.id AS course_id,
    c.name AS course_name,
    c.code AS course_code,
    c.credit,
    s.room_id,
    r.name AS room_name,
    r.building,
    s.day_of_week,
    s.start_time,
    s.end_time,
    s.weeks,
    s.semester
FROM schedule s
JOIN user u ON s.user_id = u.id
JOIN course c ON s.course_id = c.id
JOIN room r ON s.room_id = r.id
WHERE u.role = 0 AND s.is_deleted = 0;

-- ===============================================
-- 触发器：自动更新 updated_at 时间（MySQL 5.6.5+ 不需要）
-- ===============================================

DELIMITER $$
CREATE TRIGGER update_user_timestamp 
BEFORE UPDATE ON user 
FOR EACH ROW 
BEGIN
    SET NEW.updated_at = CURRENT_TIMESTAMP;
END$$
DELIMITER ;

DELIMITER $$
CREATE TRIGGER update_course_timestamp 
BEFORE UPDATE ON course 
FOR EACH ROW 
BEGIN
    SET NEW.updated_at = CURRENT_TIMESTAMP;
END$$
DELIMITER ;

-- ===============================================
-- 完成
-- ===============================================
SELECT '数据库初始化完成！' AS message;
SELECT COUNT(*) AS user_count FROM user;
SELECT COUNT(*) AS major_count FROM major;
SELECT COUNT(*) AS class_count FROM class;
SELECT COUNT(*) AS course_count FROM course;
SELECT COUNT(*) AS room_count FROM room;
SELECT COUNT(*) AS schedule_count FROM schedule;
