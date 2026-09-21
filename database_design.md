# 查课管理系统 - 数据库设计文档

> 历史数据库初稿，待重设：本文件围绕课程查询、成绩和选课建立，不覆盖当前查课提交、审核、异议、截止时间与周报版本模型。当前数据设计基线见[技术方案 V1.4 第 8–9 节](查课管理系统V1.0开发技术方案.md)。后续使用 SQLAlchemy 定义模型、Alembic 管理迁移；配套旧 database.sql 尚未转换，不可直接当作新系统建库依据。

## 一、ER 图概述

### 实体关系说明

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   User(用户) │──1:N│  Schedule(课表)│N:1│  Course(课程) │
└─────────────┘      └──────────────┘      └─────────────┘
       │                                           │
       │ 1:N                                       │ N:M
       ▼                                           ▼
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│  Grade(成绩) │      │Course_User(选课)│      │ Major(专业)  │
└─────────────┘      └──────────────┘      └─────────────┘
                                               │
                                               │ 1:N
                                               ▼
                                        ┌─────────────┐
                                        │Class(班级)  │
                                        └─────────────┘
                                               │
                                               │ N:1
                                               ▼
                                        ┌─────────────┐
                                        │Room(教室)   │
                                        └─────────────┘
```

### 核心关系说明

1. **User-Course**: 多对多关系（学生可选多门课程，教师可教授多门课程）
2. **User-Schedule**: 一对多关系（一个用户对应多个课表记录）
3. **Course-Major**: 一对多关系（一门课程属于一个专业）
4. **Course-Class**: 一对多关系（一门课程面向多个班级）
5. **Schedule-Room**: 多对一关系（多个课表可使用同一教室）

---

## 二、数据字典

### 1. 用户表 (user)

| 字段名 | 类型 | 长度 | 必填 | 默认值 | 说明 |
|--------|------|------|------|--------|------|
| id | BIGINT | 20 | ✓ | AUTO_INCREMENT | 主键 ID |
| username | VARCHAR | 50 | ✓ | - | 用户名（学号/工号） |
| password | VARCHAR | 100 | ✓ | - | 密码（加密存储） |
| nickname | VARCHAR | 50 | | NULL | 昵称 |
| avatar | VARCHAR | 255 | | NULL | 头像 URL |
| phone | VARCHAR | 20 | | NULL | 手机号 |
| email | VARCHAR | 100 | | NULL | 邮箱 |
| openid | VARCHAR | 64 | | NULL | 微信 OpenID |
| union_id | VARCHAR | 64 | | NULL | 微信 UnionID |
| role | TINYINT | 1 | ✓ | 0 | 角色：0-学生，1-教师，2-管理员 |
| major_id | BIGINT | 20 | | NULL | 所属专业 ID（学生用） |
| class_id | BIGINT | 20 | | NULL | 所属班级 ID（学生用） |
| department | VARCHAR | 100 | | NULL | 所属院系（教师用） |
| status | TINYINT | 1 | ✓ | 1 | 状态：0-禁用，1-正常 |
| created_at | DATETIME | - | ✓ | CURRENT_TIMESTAMP | 创建时间 |
| updated_at | DATETIME | - | ✓ | CURRENT_TIMESTAMP | 更新时间 |

**索引**: 
- PRIMARY KEY (id)
- UNIQUE KEY uk_username (username)
- UNIQUE KEY uk_openid (openid)
- INDEX idx_role (role)
- INDEX idx_major_id (major_id)
- INDEX idx_class_id (class_id)

---

### 2. 专业表 (major)

| 字段名 | 类型 | 长度 | 必填 | 默认值 | 说明 |
|--------|------|------|------|--------|------|
| id | BIGINT | 20 | ✓ | AUTO_INCREMENT | 主键 ID |
| name | VARCHAR | 100 | ✓ | - | 专业名称 |
| code | VARCHAR | 20 | ✓ | - | 专业代码 |
| department | VARCHAR | 100 | ✓ | - | 所属院系 |
| description | TEXT | - | | NULL | 专业描述 |
| status | TINYINT | 1 | ✓ | 1 | 状态：0-禁用，1-正常 |
| created_at | DATETIME | - | ✓ | CURRENT_TIMESTAMP | 创建时间 |
| updated_at | DATETIME | - | ✓ | CURRENT_TIMESTAMP | 更新时间 |

**索引**: 
- PRIMARY KEY (id)
- UNIQUE KEY uk_code (code)
- INDEX idx_department (department)

---

### 3. 班级表 (class)

| 字段名 | 类型 | 长度 | 必填 | 默认值 | 说明 |
|--------|------|------|------|--------|------|
| id | BIGINT | 20 | ✓ | AUTO_INCREMENT | 主键 ID |
| name | VARCHAR | 50 | ✓ | - | 班级名称（如：计算机 1 班） |
| code | VARCHAR | 20 | ✓ | - | 班级编码 |
| major_id | BIGINT | 20 | ✓ | - | 所属专业 ID |
| grade | INT | 4 | ✓ | - | 年级（如：2024） |
| year | TINYINT | 2 | ✓ | - | 年级（如：1 表示大一） |
| advisor | VARCHAR | 50 | | NULL | 班主任/辅导员 |
| student_count | INT | 6 | ✓ | 0 | 学生人数 |
| status | TINYINT | 1 | ✓ | 1 | 状态：0-禁用，1-正常 |
| created_at | DATETIME | - | ✓ | CURRENT_TIMESTAMP | 创建时间 |
| updated_at | DATETIME | - | ✓ | CURRENT_TIMESTAMP | 更新时间 |

**索引**: 
- PRIMARY KEY (id)
- UNIQUE KEY uk_code (code)
- INDEX idx_major_id (major_id)
- INDEX idx_grade_year (grade, year)

---

### 4. 课程表 (course)

| 字段名 | 类型 | 长度 | 必填 | 默认值 | 说明 |
|--------|------|------|------|--------|------|
| id | BIGINT | 20 | ✓ | AUTO_INCREMENT | 主键 ID |
| name | VARCHAR | 100 | ✓ | - | 课程名称 |
| code | VARCHAR | 50 | ✓ | - | 课程编号/课号 |
| credit | DECIMAL | 3,1 | ✓ | - | 学分 |
| hours | INT | 4 | ✓ | - | 总课时 |
| type | VARCHAR | 20 | | '必修' | 课程类型：必修/选修/通识 |
| major_id | BIGINT | 20 | | NULL | 适用专业 ID |
| teacher_id | BIGINT | 20 | | NULL | 主讲教师 ID |
| description | TEXT | - | | NULL | 课程描述 |
| prerequisite | VARCHAR | 255 | | NULL | 先修课程 |
| status | TINYINT | 1 | ✓ | 1 | 状态：0-禁用，1-正常 |
| created_at | DATETIME | - | ✓ | CURRENT_TIMESTAMP | 创建时间 |
| updated_at | DATETIME | - | ✓ | CURRENT_TIMESTAMP | 更新时间 |

**索引**: 
- PRIMARY KEY (id)
- UNIQUE KEY uk_code (code)
- INDEX idx_major_id (major_id)
- INDEX idx_teacher_id (teacher_id)

---

### 5. 教室表 (room)

| 字段名 | 类型 | 长度 | 必填 | 默认值 | 说明 |
|--------|------|------|------|--------|------|
| id | BIGINT | 20 | ✓ | AUTO_INCREMENT | 主键 ID |
| name | VARCHAR | 50 | ✓ | - | 教室名称（如：A101） |
| building | VARCHAR | 50 | ✓ | - | 所在楼栋 |
| floor | INT | 2 | | NULL | 楼层 |
| capacity | INT | 4 | | NULL | 座位数 |
| type | VARCHAR | 20 | | '普通教室' | 教室类型：普通教室/机房/实验室 |
| equipment | VARCHAR | 255 | | NULL | 设备配置（逗号分隔） |
| status | TINYINT | 1 | ✓ | 1 | 状态：0-禁用，1-可用 |
| created_at | DATETIME | - | ✓ | CURRENT_TIMESTAMP | 创建时间 |
| updated_at | DATETIME | - | ✓ | CURRENT_TIMESTAMP | 更新时间 |

**索引**: 
- PRIMARY KEY (id)
- INDEX idx_building (building)
- INDEX idx_type (type)

---

### 6. 课表表 (schedule)

| 字段名 | 类型 | 长度 | 必填 | 默认值 | 说明 |
|--------|------|------|------|--------|------|
| id | BIGINT | 20 | ✓ | AUTO_INCREMENT | 主键 ID |
| course_id | BIGINT | 20 | ✓ | - | 课程 ID |
| user_id | BIGINT | 20 | ✓ | - | 用户 ID |
| class_id | BIGINT | 20 | | NULL | 班级 ID |
| room_id | BIGINT | 20 | ✓ | - | 教室 ID |
| week_start | INT | 2 | ✓ | - | 周次开始（1-18） |
| week_end | INT | 2 | ✓ | - | 周次结束（1-18） |
| day_of_week | TINYINT | 1 | ✓ | - | 星期几（1-7，1 为周一） |
| start_time | TIME | - | ✓ | - | 开始时间 |
| end_time | TIME | - | ✓ | - | 结束时间 |
| weeks | VARCHAR | 50 | | NULL | 具体周数（如：1-10,12-18） |
| semester | VARCHAR | 20 | ✓ | - | 学期（如：2024-2025 上学期） |
| academic_year | VARCHAR | 9 | ✓ | - | 学年（如：2024-2025） |
| is_deleted | TINYINT | 1 | ✓ | 0 | 删除标记：0-未删除，1-已删除 |
| created_at | DATETIME | - | ✓ | CURRENT_TIMESTAMP | 创建时间 |
| updated_at | DATETIME | - | ✓ | CURRENT_TIMESTAMP | 更新时间 |

**索引**: 
- PRIMARY KEY (id)
- INDEX idx_course_id (course_id)
- INDEX idx_user_id (user_id)
- INDEX idx_class_id (class_id)
- INDEX idx_room_id (room_id)
- INDEX idx_day_time (day_of_week, start_time)
- INDEX idx_semester (semester)

---

### 7. 成绩表 (grade)

| 字段名 | 类型 | 长度 | 必填 | 默认值 | 说明 |
|--------|------|------|------|--------|------|
| id | BIGINT | 20 | ✓ | AUTO_INCREMENT | 主键 ID |
| user_id | BIGINT | 20 | ✓ | - | 学生 ID |
| course_id | BIGINT | 20 | ✓ | - | 课程 ID |
| schedule_id | BIGINT | 20 | | NULL | 课表 ID |
| score | DECIMAL | 4,1 | | NULL | 成绩（0-100） |
| grade_level | VARCHAR | 2 | | NULL | 等级（A/B/C/D/E） |
| exam_type | VARCHAR | 20 | | '期末' | 考试类型：平时/期中/期末/其他 |
| remark | VARCHAR | 255 | | NULL | 备注 |
| created_at | DATETIME | - | ✓ | CURRENT_TIMESTAMP | 创建时间 |
| updated_at | DATetime | - | ✓ | CURRENT_TIMESTAMP | 更新时间 |

**索引**: 
- PRIMARY KEY (id)
- UNIQUE KEY uk_user_course (user_id, course_id)
- INDEX idx_user_id (user_id)
- INDEX idx_course_id (course_id)

---

### 8. 选课记录表 (course_user)

| 字段名 | 类型 | 长度 | 必填 | 默认值 | 说明 |
|--------|------|------|------|--------|------|
| id | BIGINT | 20 | ✓ | AUTO_INCREMENT | 主键 ID |
| user_id | BIGINT | 20 | ✓ | - | 用户 ID |
| course_id | BIGINT | 20 | ✓ | - | 课程 ID |
| semester | VARCHAR | 20 | ✓ | - | 学期 |
| status | TINYINT | 1 | ✓ | 1 | 状态：0-退课，1-正常，2-已毕业 |
| added_at | DATETIME | - | ✓ | CURRENT_TIMESTAMP | 添加时间 |
| updated_at | DATETIME | - | ✓ | CURRENT_TIMESTAMP | 更新时间 |

**索引**: 
- PRIMARY KEY (id)
- UNIQUE KEY uk_user_course (user_id, course_id, semester)
- INDEX idx_user_id (user_id)
- INDEX idx_course_id (course_id)

---

### 9. 操作日志表 (operation_log)

| 字段名 | 类型 | 长度 | 必填 | 默认值 | 说明 |
|--------|------|------|------|--------|------|
| id | BIGINT | 20 | ✓ | AUTO_INCREMENT | 主键 ID |
| user_id | BIGINT | 20 | | NULL | 操作用户 ID |
| action | VARCHAR | 50 | ✓ | - | 操作类型（查询/新增/修改/删除） |
| module | VARCHAR | 50 | ✓ | - | 模块名称 |
| content | TEXT | - | | NULL | 操作内容 JSON |
| ip | VARCHAR | 50 | | NULL | IP 地址 |
| user_agent | VARCHAR | 500 | | NULL | 用户代理 |
| created_at | DATETIME | - | ✓ | CURRENT_TIMESTAMP | 创建时间 |

**索引**: 
- PRIMARY KEY (id)
- INDEX idx_user_id (user_id)
- INDEX idx_action (action)
- INDEX idx_created_at (created_at)

---

## 三、字段枚举值说明

### 用户角色 (user.role)
- `0`: 学生
- `1`: 教师
- `2`: 管理员

### 课程类型 (course.type)
- `必修`: 必修课
- `选修`: 选修课
- `通识`: 通识教育课

### 教室类型 (room.type)
- `普通教室`: 普通教室
- `机房`: 计算机房
- `实验室`: 专业实验室
- `报告厅`: 报告厅

### 状态标识 (status/is_deleted)
- `0`: 禁用/已删除
- `1`: 正常/未删除

---

## 四、数据库设计原则

1. **命名规范**: 使用下划线命名法，表名和字段名全小写
2. **主键设计**: 所有表使用 BIGINT 自增主键
3. **时间字段**: 统一使用 DATETIME 类型，包含 created_at 和 updated_at
4. **软删除**: 重要表使用 is_deleted 字段实现软删除
5. **字符集**: 统一使用 utf8mb4 字符集
6. **引擎**: 使用 InnoDB 引擎支持事务
