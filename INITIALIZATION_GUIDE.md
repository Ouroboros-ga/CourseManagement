# 查课管理系统 - 项目初始化指南

## 📦 已完成的工作

### ✅ 1. Git 仓库配置
- **文件**: `.gitignore`
- **内容**: 
  - Java/Maven 编译产物
  - IDE 配置文件（IntelliJ IDEA、Eclipse、VS Code）
  - 系统临时文件（macOS/Windows/Linux）
  - 日志和临时文件

### ✅ 2. 数据库设计文档
- **文件**: `database_design.md`
- **包含内容**:
  - ER 图（实体关系图）
  - 9 张核心数据表的设计
  - 字段类型、索引、约束说明
  - 枚举值定义
  - 数据库设计原则

### ✅ 3. 数据库 SQL 脚本
- **文件**: `database.sql`
- **功能**:
  - 创建数据库 `course_management`
  - 创建 9 张数据表
  - 插入示例初始数据
  - 创建视图和触发器

---

## 🚀 下一步开发步骤

### 第一阶段：后端开发（预计 1-2 周）

#### Step 1: 创建 Spring Boot 项目结构

```bash
# 在项目根目录执行
mkdir backend
cd backend

# 使用 IntelliJ IDEA 或 Spring Initializr 创建项目
# 推荐依赖：
# - Spring Web
# - Spring Data JPA / MyBatis
# - MySQL Driver
# - Lombok
# - Validation
# - JWT
# - Spring Security (可选)
```

#### Step 2: 项目目录结构规划

```
backend/
├── src/main/java/com/course/management/
│   ├── CourseManagementApplication.java
│   ├── config/                    # 配置类
│   │   ├── SwaggerConfig.java
│   │   ├── MyBatisConfig.java
│   │   └── SecurityConfig.java
│   ├── controller/               # 控制器层
│   │   ├── UserController.java
│   │   ├── CourseController.java
│   │   ├── ScheduleController.java
│   │   └── AdminController.java
│   ├── service/                  # 业务逻辑层
│   │   ├── UserService.java
│   │   ├── CourseService.java
│   │   └── impl/
│   ├── mapper/                   # DAO 层
│   │   ├── UserMapper.java
│   │   ├── CourseMapper.java
│   │   └── ScheduleMapper.java
│   ├── entity/                   # 实体类
│   │   ├── User.java
│   │   ├── Course.java
│   │   └── Schedule.java
│   ├── dto/                      # 数据传输对象
│   │   ├── request/
│   │   └── response/
│   ├── common/                   # 通用组件
│   │   ├── Result.java          # 统一返回结果
│   │   ├── PageResult.java      # 分页结果
│   │   ├── Constant.java        # 常量定义
│   │   └── exception/           # 异常处理
│   ├── util/                     # 工具类
│   │   ├── JwtUtil.java
│   │   └── PasswordUtil.java
│   └── scheduler/                # 定时任务
│       └── CleanLogTask.java
├── src/main/resources/
│   ├── application.yml           # 配置文件
│   ├── application-dev.yml       # 开发环境
│   ├── application-prod.yml      # 生产环境
│   └── mapper/                   # MyBatis XML
├── src/test/java/                # 测试代码
├── pom.xml                       # Maven 配置
└── README.md
```

#### Step 3: 配置文件模板

**application.yml**
```yaml
server:
  port: 8080
  servlet:
    context-path: /api

spring:
  application:
    name: course-management
  profiles:
    active: dev
  
mybatis:
  mapper-locations: classpath:mapper/*.xml
  type-aliases-package: com.course.management.entity
  configuration:
    map-underscore-to-camel-case: true
    log-impl: org.apache.ibatis.logging.stdout.StdOutImpl

logging:
  level:
    com.course.management.mapper: debug
  file:
    path: logs
```

**application-dev.yml**
```yaml
spring:
  datasource:
    driver-class-name: com.mysql.cj.jdbc.Driver
    url: jdbc:mysql://localhost:3306/course_management?useUnicode=true&characterEncoding=utf8&useSSL=false&serverTimezone=Asia/Shanghai
    username: root
    password: your_password
    
  jwt:
    secret: your-secret-key-here
    expiration: 86400000  # 24 小时（毫秒）
```

---

### 第二阶段：核心功能开发

#### 模块 1：用户认证模块
- [ ] 微信登录接口
- [ ] JWT 令牌生成与验证
- [ ] 用户信息管理
- [ ] 角色权限控制

#### 模块 2：课程查询模块
- [ ] 课程列表查询（支持多条件筛选）
- [ ] 课程详情查看
- [ ] 个人课表展示
- [ ] 空闲教室查询

#### 模块 3：管理后台
- [ ] 用户管理（增删改查）
- [ ] 课程管理（排课、调课）
- [ ] 专业班级管理
- [ ] 数据统计看板

#### 模块 4：小程序前端
- [ ] 项目框架搭建
- [ ] 登录页面
- [ ] 首页（搜索入口）
- [ ] 课程列表页
- [ ] 课表详情页
- [ ] 个人中心页

---

## 📝 开发规范

### 1. API 设计规范
```
GET    /api/users              # 获取用户列表
POST   /api/users              # 创建用户
GET    /api/users/{id}         # 获取指定用户
PUT    /api/users/{id}         # 更新用户
DELETE /api/users/{id}         # 删除用户

GET    /api/courses            # 获取课程列表
POST   /api/courses/search     # 高级搜索
GET    /api/schedules/my       # 获取我的课表
```

### 2. 统一返回格式
```json
{
  "code": 200,
  "message": "success",
  "data": {},
  "timestamp": 1695200000000
}
```

### 3. 错误码规范
```
200  - 成功
400  - 请求参数错误
401  - 未授权
403  - 禁止访问
404  - 资源不存在
500  - 服务器内部错误

业务错误码：
10001 - 用户不存在
10002 - 密码错误
10003 - 用户名已存在
```

---

## 🔧 开发环境准备

### 必需软件
- JDK 21 (已安装：`E:/java/jdk-21`)
- Node.js 24.14.1 (已安装)
- MySQL 8.0+
- Maven 3.8+
- IntelliJ IDEA 2026.2.3 (已安装)
- 微信开发者工具

### 数据库初始化步骤
```sql
-- 1. 登录 MySQL
mysql -u root -p

-- 2. 执行 SQL 脚本
source D:/My project/CourseManagement/database.sql

-- 3. 验证数据
USE course_management;
SHOW TABLES;
SELECT * FROM user;
```

---

## 📊 技术栈选择建议

### 后端技术栈
| 技术 | 版本 | 说明 |
|------|------|------|
| Java | 21 | 开发语言 |
| Spring Boot | 3.2.x | 应用框架 |
| MyBatis-Plus | 3.5.x | ORM 框架 |
| MySQL | 8.0+ | 数据库 |
| Redis | 7.0+ | 缓存（可选） |
| JWT | - | 令牌认证 |
| Lombok | - | 简化代码 |
| Swagger/Knife4j | - | API 文档 |

### 前端技术栈（小程序）
| 技术 | 说明 |
|------|------|
| 微信小程序原生 | WXML + WXSS + JavaScript |
| WeUI | 微信官方 UI 组件库 |

---

## ⏱️ 时间估算

| 阶段 | 工作内容 | 预计时间 |
|------|----------|----------|
| 第 1 周 | 后端基础框架搭建 + 用户模块 | 5 天 |
| 第 2 周 | 课程查询功能 + 管理后台 | 5 天 |
| 第 3 周 | 小程序前端开发 | 5 天 |
| 第 4 周 | 联调测试 + Bug 修复 | 5 天 |
| **总计** | | **约 20 个工作日** |

---

## 🎯 里程碑目标

### M1: 后端基础完成（Week 1）
- [x] 数据库设计与创建
- [ ] Spring Boot 项目搭建
- [ ] 用户登录功能实现
- [ ] 基础 CRUD 接口

### M2: 核心功能完成（Week 2-3）
- [ ] 课程查询功能
- [ ] 课表展示功能
- [ ] 管理后台基础功能

### M3: 小程序上线（Week 4）
- [ ] 小程序所有页面开发完成
- [ ] 前后端联调通过
- [ ] 性能优化与安全加固
- [ ] 部署上线

---

## 💡 建议

1. **立即开始**: 先创建 Spring Boot 项目，快速搭建基础框架
2. **优先核心**: 先做用户登录和课程查询这两个核心功能
3. **边做边测**: 每完成一个接口就进行测试
4. **文档同步**: 编写 API 文档方便前端对接
5. **版本管理**: 每次完成一个小功能就提交一次 Git
