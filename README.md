# 查课管理系统 V1.0

> Java 原生微信小程序版

## 📖 项目简介

查课管理系统是一个基于 Spring Boot + 微信小程序的教务管理平台，主要功能包括课程查询、课表查看、教室空闲查询等，旨在提高高校教务管理信息化水平。

### 技术栈

- **后端**: Java 21 + Spring Boot 3.2 + MyBatis + MySQL
- **前端**: 微信小程序原生开发
- **认证**: JWT + 微信登录
- **开发工具**: IntelliJ IDEA + 微信开发者工具

---

## 🎯 核心功能

### 用户端（小程序）
- ✅ 微信一键登录
- ✅ 多维度课程搜索
- ✅ 个人课表查看
- ✅ 空闲教室查询
- ✅ 个人信息管理

### 管理端（后台）
- 👤 用户管理（学生/教师）
- 📚 课程信息管理
- 📅 排课与调课
- 🏫 教室资源管理
- 📊 数据统计分析

---

## 📁 项目结构

```
CourseManagement/
├── .gitignore                    # Git 忽略文件配置
├── database.sql                  # 数据库初始化脚本
├── database_design.md            # 数据库设计文档（ER 图 + 数据字典）
├── INITIALIZATION_GUIDE.md       # 项目初始化指南
├── 查课管理系统 V1.0 开发技术方案-Java 原生微信小程序版.md  # 详细技术方案
└── backend/                      # 后端代码（待创建）
    └── src/main/java/...
    
└── miniprogram/                  # 小程序代码（待创建）
    └── pages/...
```

---

## 🚀 快速开始

### 环境要求

- JDK 21+
- Node.js 16+
- MySQL 8.0+
- Maven 3.8+
- IntelliJ IDEA 2026.2.3
- 微信开发者工具

### 数据库初始化

```bash
# 1. 登录 MySQL
mysql -u root -p

# 2. 执行初始化脚本
source D:/My project/CourseManagement/database.sql

# 3. 验证
USE course_management;
SHOW TABLES;
```

### 后端启动

```bash
cd backend
mvn clean install
java -jar target/course-management.jar
```

访问 `http://localhost:8080/api` 查看 API 接口

### 小程序运行

```bash
# 使用微信开发者工具打开 miniprogram 目录
# 配置 appid 和服务器域名
# 点击编译运行
```

---

## 📚 文档导航

| 文档 | 说明 |
|------|------|
| [INITIALIZATION_GUIDE.md](./INITIALIZATION_GUIDE.md) | 项目初始化指南，包含开发步骤和时间规划 |
| [database_design.md](./database_design.md) | 数据库 ER 图和完整数据字典 |
| [database.sql](./database.sql) | 数据库建表 SQL 脚本 |
| [技术方案文档](./查课管理系统 V1.0 开发技术方案-Java 原生微信小程序版.md) | 详细的技术架构和功能设计 |

---

## 🗂️ 数据库表清单

| 表名 | 说明 | 字段数 |
|------|------|--------|
| user | 用户表 | 17 |
| major | 专业表 | 9 |
| class | 班级表 | 11 |
| course | 课程表 | 13 |
| room | 教室表 | 9 |
| schedule | 课表表 | 16 |
| grade | 成绩表 | 9 |
| course_user | 选课记录表 | 7 |
| operation_log | 操作日志表 | 8 |

---

## 👥 角色权限

| 角色 | 说明 | 权限 |
|------|------|------|
| 学生 | 普通用户 | 查询课程、查看课表、管理个人信息 |
| 教师 | 教职工 | 查询课程、管理授课信息、查看学生名单 |
| 管理员 | 系统管理员 | 所有功能权限 |

---

## 🔐 安全说明

- 密码采用 BCrypt 加密存储
- API 使用 JWT 令牌认证
- 敏感操作记录日志
- 支持 IP 白名单限制

---

## 📝 开发计划

### v1.0 (当前版本)
- [x] 数据库设计与初始化
- [ ] 后端基础框架搭建
- [ ] 用户认证模块
- [ ] 课程查询功能
- [ ] 小程序前端开发
- [ ] 联调测试

### v1.1 (计划中)
- 消息通知功能
- 数据导出功能
- 智能推荐课程

### v2.0 (规划中)
- 在线选课功能
- 成绩管理系统
- 移动端 App

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

---

## 📄 开源协议

本项目采用 MIT 开源协议

---

## 📧 联系方式

- GitHub: [Ouroboros-ga](https://github.com/Ouroboros-ga)
- Repository: [CourseManagement](https://github.com/Ouroboros-ga/CourseManagement.git)

---

## 🙏 致谢

感谢所有为开源社区做出贡献的开发者！

---

<div align="center">

**查课管理系统 V1.0**  
Made with ❤️ by CourseManagement Team

</div>
