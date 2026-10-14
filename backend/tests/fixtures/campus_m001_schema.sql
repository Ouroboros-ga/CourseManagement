BEGIN TRANSACTION;
CREATE TABLE administrative_class (
	id INTEGER NOT NULL,
	class_code VARCHAR(64) NOT NULL,
	class_name VARCHAR(128) NOT NULL,
	grade_year INTEGER,
	major_name VARCHAR(128),
	college VARCHAR(128),
	head_teacher VARCHAR(64),
	counselor VARCHAR(64),
	status VARCHAR(16) DEFAULT 'ACTIVE' NOT NULL,
	college_id INTEGER,
	ownership_version INTEGER DEFAULT 1 NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_administrative_class PRIMARY KEY (id),
	CONSTRAINT uq_administrative_class_class_code UNIQUE (class_code),
	CONSTRAINT fk_administrative_class_college_id_college FOREIGN KEY(college_id) REFERENCES college (id) ON DELETE RESTRICT
);
CREATE TABLE assignment_change_request (
	id INTEGER NOT NULL,
	assignment_id INTEGER NOT NULL,
	request_user_id INTEGER NOT NULL,
	reason VARCHAR(512) NOT NULL,
	status VARCHAR(16) DEFAULT 'PENDING' NOT NULL,
	processed_by INTEGER,
	processed_at DATETIME,
	comment VARCHAR(512),
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_assignment_change_request PRIMARY KEY (id),
	CONSTRAINT ck_assignment_change_request_ck_assignment_change_request_status CHECK (status IN ('PENDING','APPROVED','REJECTED')),
	CONSTRAINT fk_assignment_change_request_assignment_id_inspection_assignment FOREIGN KEY(assignment_id) REFERENCES inspection_assignment (id) ON DELETE CASCADE,
	CONSTRAINT fk_assignment_change_request_request_user_id_user_account FOREIGN KEY(request_user_id) REFERENCES user_account (id) ON DELETE RESTRICT,
	CONSTRAINT fk_assignment_change_request_processed_by_user_account FOREIGN KEY(processed_by) REFERENCES user_account (id) ON DELETE SET NULL
);
CREATE TABLE attendance_record (
	id INTEGER NOT NULL,
	task_id INTEGER NOT NULL,
	student_id INTEGER NOT NULL,
	effective_type VARCHAR(16) NOT NULL,
	current_version INTEGER DEFAULT 1 NOT NULL,
	source_submission_item_id INTEGER,
	created_at DATETIME NOT NULL,
	CONSTRAINT pk_attendance_record PRIMARY KEY (id),
	CONSTRAINT uq_attendance_record_task_stu UNIQUE (task_id, student_id),
	CONSTRAINT ck_attendance_record_ck_attendance_record_effective_type CHECK (effective_type IN ('NORMAL','LEAVE','LATE','ABSENT')),
	CONSTRAINT ck_attendance_record_ck_attendance_record_current_version CHECK (current_version >= 1),
	CONSTRAINT fk_attendance_record_task_id_inspection_task FOREIGN KEY(task_id) REFERENCES inspection_task (id) ON DELETE CASCADE,
	CONSTRAINT fk_attendance_record_student_id_student FOREIGN KEY(student_id) REFERENCES student (id) ON DELETE RESTRICT,
	CONSTRAINT fk_attendance_record_source_submission_item_id_submission_abnormal_item FOREIGN KEY(source_submission_item_id) REFERENCES submission_abnormal_item (id) ON DELETE SET NULL
);
CREATE TABLE attendance_record_version (
	id INTEGER NOT NULL,
	attendance_record_id INTEGER NOT NULL,
	version_no INTEGER NOT NULL,
	attendance_type VARCHAR(16) NOT NULL,
	source_type VARCHAR(16) NOT NULL,
	source_id INTEGER,
	changed_by INTEGER,
	reason VARCHAR(512),
	created_at DATETIME NOT NULL,
	CONSTRAINT pk_attendance_record_version PRIMARY KEY (id),
	CONSTRAINT uq_attendance_record_version_rec_no UNIQUE (attendance_record_id, version_no),
	CONSTRAINT ck_attendance_record_version_ck_attendance_record_version_type CHECK (attendance_type IN ('NORMAL','LEAVE','LATE','ABSENT')),
	CONSTRAINT ck_attendance_record_version_ck_attendance_record_version_source_type CHECK (source_type IN ('SUBMISSION','CORRECTION','OBJECTION_FINAL')),
	CONSTRAINT fk_attendance_record_version_attendance_record_id_attendance_record FOREIGN KEY(attendance_record_id) REFERENCES attendance_record (id) ON DELETE CASCADE,
	CONSTRAINT fk_attendance_record_version_changed_by_user_account FOREIGN KEY(changed_by) REFERENCES user_account (id) ON DELETE SET NULL
);
CREATE TABLE audit_log (
	id INTEGER NOT NULL,
	actor_user_id INTEGER,
	action VARCHAR(64) NOT NULL,
	resource_type VARCHAR(64) NOT NULL,
	resource_id VARCHAR(64),
	before_json JSON,
	after_json JSON,
	reason VARCHAR(512),
	request_id VARCHAR(64),
	created_at DATETIME NOT NULL,
	CONSTRAINT pk_audit_log PRIMARY KEY (id),
	CONSTRAINT fk_audit_log_actor_user_id_user_account FOREIGN KEY(actor_user_id) REFERENCES user_account (id) ON DELETE SET NULL
);
CREATE TABLE auth_session (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	client_type VARCHAR(16) NOT NULL,
	refresh_token_hash VARCHAR(64) NOT NULL,
	refresh_family_id VARCHAR(36) NOT NULL,
	expires_at DATETIME NOT NULL,
	revoked_at DATETIME,
	last_used_at DATETIME,
	created_at DATETIME NOT NULL,
	CONSTRAINT pk_auth_session PRIMARY KEY (id),
	CONSTRAINT fk_auth_session_user_id_user_account FOREIGN KEY(user_id) REFERENCES user_account (id) ON DELETE CASCADE
);
CREATE TABLE calendar_override (
	id INTEGER NOT NULL,
	semester_id INTEGER NOT NULL,
	date DATE NOT NULL,
	override_type VARCHAR(16) NOT NULL,
	source_teaching_week INTEGER,
	source_teaching_weekday INTEGER,
	reason VARCHAR(255),
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_calendar_override PRIMARY KEY (id),
	CONSTRAINT ck_calendar_override_ck_calendar_override_type CHECK (override_type IN ('STOP','MAKEUP')),
	CONSTRAINT ck_calendar_override_ck_calendar_override_source_week_positive CHECK (source_teaching_week IS NULL OR source_teaching_week >= 1),
	CONSTRAINT uq_calendar_override_sem_date UNIQUE (semester_id, date),
	CONSTRAINT fk_calendar_override_semester_id_semester FOREIGN KEY(semester_id) REFERENCES semester (id) ON DELETE RESTRICT
);
CREATE TABLE college (
	id INTEGER NOT NULL,
	school_id INTEGER NOT NULL,
	code VARCHAR(32) NOT NULL,
	name VARCHAR(128) NOT NULL,
	status VARCHAR(16) NOT NULL,
	lock_version INTEGER NOT NULL,
	authorization_revision INTEGER NOT NULL,
	configuration_revision INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_college PRIMARY KEY (id),
	CONSTRAINT uq_college_school_code UNIQUE (school_id, code),
	CONSTRAINT ck_college_college_status CHECK (status IN ('ACTIVE','INACTIVE')),
	CONSTRAINT fk_college_school_id_school FOREIGN KEY(school_id) REFERENCES school (id) ON DELETE RESTRICT
);
CREATE TABLE course (
	id INTEGER NOT NULL,
	course_code VARCHAR(64) NOT NULL,
	course_name VARCHAR(128) NOT NULL,
	status VARCHAR(16) DEFAULT 'ACTIVE' NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_course PRIMARY KEY (id),
	CONSTRAINT uq_course_course_code UNIQUE (course_code)
);
CREATE TABLE course_schedule (
	id INTEGER NOT NULL,
	semester_id INTEGER NOT NULL,
	teaching_class_id INTEGER NOT NULL,
	weekday INTEGER NOT NULL,
	start_period INTEGER NOT NULL,
	end_period INTEGER NOT NULL,
	classroom VARCHAR(128),
	teacher VARCHAR(128),
	status VARCHAR(16) DEFAULT 'ACTIVE' NOT NULL,
	college_id INTEGER,
	ownership_version INTEGER DEFAULT 1 NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_course_schedule PRIMARY KEY (id),
	CONSTRAINT ck_course_schedule_ck_course_schedule_weekday CHECK (weekday BETWEEN 1 AND 7),
	CONSTRAINT ck_course_schedule_ck_course_schedule_period_range CHECK (end_period >= start_period),
	CONSTRAINT fk_course_schedule_semester_id_semester FOREIGN KEY(semester_id) REFERENCES semester (id) ON DELETE RESTRICT,
	CONSTRAINT fk_course_schedule_teaching_class_id_teaching_class FOREIGN KEY(teaching_class_id) REFERENCES teaching_class (id) ON DELETE RESTRICT,
	CONSTRAINT fk_course_schedule_college_id_college FOREIGN KEY(college_id) REFERENCES college (id) ON DELETE RESTRICT
);
CREATE TABLE course_schedule_week (
	id INTEGER NOT NULL,
	schedule_id INTEGER NOT NULL,
	week_no INTEGER NOT NULL,
	CONSTRAINT pk_course_schedule_week PRIMARY KEY (id),
	CONSTRAINT uq_schedule_week UNIQUE (schedule_id, week_no),
	CONSTRAINT fk_course_schedule_week_schedule_id_course_schedule FOREIGN KEY(schedule_id) REFERENCES course_schedule (id) ON DELETE CASCADE
);
CREATE TABLE course_type (
	id INTEGER NOT NULL,
	college_id INTEGER NOT NULL,
	code VARCHAR(32) NOT NULL,
	name VARCHAR(128) NOT NULL,
	normalized_name VARCHAR(128) NOT NULL,
	description VARCHAR(512) NOT NULL,
	display_color VARCHAR(7) NOT NULL,
	sort_order INTEGER NOT NULL,
	status VARCHAR(16) NOT NULL,
	lock_version INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_course_type PRIMARY KEY (id),
	CONSTRAINT uq_course_type_college_id UNIQUE (college_id, id),
	CONSTRAINT uq_course_type_college_code UNIQUE (college_id, code),
	CONSTRAINT uq_course_type_college_name UNIQUE (college_id, normalized_name),
	CONSTRAINT ck_course_type_course_type_status CHECK (status IN ('ACTIVE','INACTIVE')),
	CONSTRAINT fk_course_type_college_id_college FOREIGN KEY(college_id) REFERENCES college (id) ON DELETE RESTRICT
);
CREATE TABLE file_object (
	id INTEGER NOT NULL,
	object_key VARCHAR(255) NOT NULL,
	category VARCHAR(24) NOT NULL,
	original_name VARCHAR(255),
	content_type VARCHAR(128) NOT NULL,
	size_bytes BIGINT NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	uploader_user_id INTEGER,
	status VARCHAR(16) DEFAULT 'UPLOADING' NOT NULL,
	retention_policy_version INTEGER DEFAULT 1 NOT NULL,
	expires_at DATETIME,
	purged_at DATETIME,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_file_object PRIMARY KEY (id),
	CONSTRAINT ck_file_object_ck_file_object_status CHECK (status IN ('UPLOADING','READY','PURGE_PENDING','PURGED','FAILED')),
	CONSTRAINT ck_file_object_ck_file_object_category CHECK (category IN ('SUBMISSION_PHOTO','OBJECTION_PROOF','IMPORT_FILE','REPORT_FILE','TEMP')),
	CONSTRAINT ck_file_object_ck_file_object_size CHECK (size_bytes >= 0),
	CONSTRAINT uq_file_object_object_key UNIQUE (object_key),
	CONSTRAINT fk_file_object_uploader_user_id_user_account FOREIGN KEY(uploader_user_id) REFERENCES user_account (id) ON DELETE SET NULL
);
CREATE TABLE group_config_version (
	id INTEGER NOT NULL,
	college_id INTEGER NOT NULL,
	group_id INTEGER NOT NULL,
	version INTEGER NOT NULL,
	configuration JSON NOT NULL,
	published_by INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_group_config_version PRIMARY KEY (id),
	CONSTRAINT fk_group_config_version_college_id_volunteer_group FOREIGN KEY(college_id, group_id) REFERENCES volunteer_group (college_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_group_config_version UNIQUE (group_id, version),
	CONSTRAINT uq_group_config_college_id UNIQUE (college_id, id),
	CONSTRAINT fk_group_config_version_college_id_college FOREIGN KEY(college_id) REFERENCES college (id) ON DELETE RESTRICT,
	CONSTRAINT fk_group_config_version_published_by_user_account FOREIGN KEY(published_by) REFERENCES user_account (id) ON DELETE RESTRICT
);
CREATE TABLE group_scope_type (
	config_id INTEGER NOT NULL,
	course_type_id INTEGER NOT NULL,
	college_id INTEGER NOT NULL,
	is_inspection_scope BOOLEAN NOT NULL,
	CONSTRAINT pk_group_scope_type PRIMARY KEY (config_id, course_type_id),
	CONSTRAINT fk_group_scope_type_college_id_group_config_version FOREIGN KEY(college_id, config_id) REFERENCES group_config_version (college_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_group_scope_type_college_id_course_type FOREIGN KEY(college_id, course_type_id) REFERENCES course_type (college_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_group_scope_type_college_id_college FOREIGN KEY(college_id) REFERENCES college (id) ON DELETE RESTRICT
);
CREATE TABLE identity_binding_token (
	id INTEGER NOT NULL,
	student_id INTEGER NOT NULL,
	token_hash VARCHAR(64) NOT NULL,
	status VARCHAR(16) DEFAULT 'UNUSED' NOT NULL,
	expires_at DATETIME NOT NULL,
	used_at DATETIME,
	failed_attempts INTEGER DEFAULT 0 NOT NULL,
	created_at DATETIME NOT NULL,
	CONSTRAINT pk_identity_binding_token PRIMARY KEY (id),
	CONSTRAINT ck_identity_binding_token_ck_status_enum CHECK (status IN ('UNUSED','USED','EXPIRED')),
	CONSTRAINT fk_identity_binding_token_student_id_student FOREIGN KEY(student_id) REFERENCES student (id) ON DELETE RESTRICT
);
CREATE TABLE import_batch (
	id INTEGER NOT NULL,
	target VARCHAR(32) NOT NULL,
	status VARCHAR(16) DEFAULT '''PREVIEW''' NOT NULL,
	semester_id INTEGER,
	teaching_class_id INTEGER,
	created_by INTEGER,
	filename VARCHAR(255),
	payload_json JSON,
	summary_json JSON,
	error_json JSON,
	expires_at DATETIME NOT NULL,
	college_id INTEGER,
	ownership_version INTEGER DEFAULT 1 NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_import_batch PRIMARY KEY (id),
	CONSTRAINT ck_import_batch_ck_import_batch_target CHECK (target IN ('roster','timetable','volunteer','admin_roster','grid_timetable','elective_course')),
	CONSTRAINT ck_import_batch_ck_import_batch_status CHECK (status IN ('PREVIEW','CONFIRMED','FAILED','EXPIRED')),
	CONSTRAINT fk_import_batch_semester_id_semester FOREIGN KEY(semester_id) REFERENCES semester (id) ON DELETE SET NULL,
	CONSTRAINT fk_import_batch_teaching_class_id_teaching_class FOREIGN KEY(teaching_class_id) REFERENCES teaching_class (id) ON DELETE SET NULL,
	CONSTRAINT fk_import_batch_created_by_user_account FOREIGN KEY(created_by) REFERENCES user_account (id) ON DELETE SET NULL,
	CONSTRAINT fk_import_batch_college_id_college FOREIGN KEY(college_id) REFERENCES college (id) ON DELETE RESTRICT
);
CREATE TABLE inspection_assignment (
	id INTEGER NOT NULL,
	task_id INTEGER NOT NULL,
	revoked_at DATETIME,
	active_task_id INTEGER GENERATED ALWAYS AS (CASE WHEN revoked_at IS NULL THEN task_id ELSE NULL END) STORED,
	volunteer_user_id INTEGER NOT NULL,
	assign_method VARCHAR(16) NOT NULL,
	assign_reason VARCHAR(512),
	assigned_by INTEGER,
	lock_version INTEGER DEFAULT 0 NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_inspection_assignment PRIMARY KEY (id),
	CONSTRAINT ck_inspection_assignment_ck_inspection_assignment_method CHECK (assign_method IN ('AUTO','MANUAL')),
	CONSTRAINT uq_inspection_assignment_active_task_id UNIQUE (active_task_id),
	CONSTRAINT fk_inspection_assignment_task_id_inspection_task FOREIGN KEY(task_id) REFERENCES inspection_task (id) ON DELETE RESTRICT,
	CONSTRAINT fk_inspection_assignment_volunteer_user_id_user_account FOREIGN KEY(volunteer_user_id) REFERENCES user_account (id) ON DELETE RESTRICT,
	CONSTRAINT fk_inspection_assignment_assigned_by_user_account FOREIGN KEY(assigned_by) REFERENCES user_account (id) ON DELETE SET NULL
);
CREATE TABLE inspection_submission (
	id INTEGER NOT NULL,
	task_id INTEGER NOT NULL,
	attempt_no INTEGER NOT NULL,
	volunteer_user_id INTEGER NOT NULL,
	roster_version INTEGER NOT NULL,
	result VARCHAR(16) NOT NULL,
	review_status VARCHAR(16) DEFAULT 'PENDING' NOT NULL,
	submitted_at DATETIME NOT NULL,
	deadline_version_id INTEGER,
	late_at_submission BOOLEAN DEFAULT 0 NOT NULL,
	note VARCHAR(512),
	reviewed_by INTEGER,
	reviewed_at DATETIME,
	review_comment VARCHAR(512),
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_inspection_submission PRIMARY KEY (id),
	CONSTRAINT uq_inspection_submission_task_attempt UNIQUE (task_id, attempt_no),
	CONSTRAINT ck_inspection_submission_ck_inspection_submission_result CHECK (result IN ('NORMAL','ABNORMAL')),
	CONSTRAINT ck_inspection_submission_ck_inspection_submission_review_status CHECK (review_status IN ('PENDING','APPROVED','REJECTED')),
	CONSTRAINT fk_inspection_submission_task_id_inspection_task FOREIGN KEY(task_id) REFERENCES inspection_task (id) ON DELETE CASCADE,
	CONSTRAINT fk_inspection_submission_volunteer_user_id_user_account FOREIGN KEY(volunteer_user_id) REFERENCES user_account (id) ON DELETE RESTRICT,
	CONSTRAINT fk_inspection_submission_deadline_version_id_submission_deadline_version FOREIGN KEY(deadline_version_id) REFERENCES submission_deadline_version (id) ON DELETE RESTRICT,
	CONSTRAINT fk_inspection_submission_reviewed_by_user_account FOREIGN KEY(reviewed_by) REFERENCES user_account (id) ON DELETE SET NULL
);
CREATE TABLE inspection_task (
	id INTEGER NOT NULL,
	task_key VARCHAR(191) NOT NULL,
	semester_id INTEGER NOT NULL,
	inspection_date DATE NOT NULL,
	week_no INTEGER NOT NULL,
	inspection_type VARCHAR(16) NOT NULL,
	start_period INTEGER NOT NULL,
	end_period INTEGER NOT NULL,
	course_schedule_id INTEGER,
	teaching_class_id INTEGER,
	administrative_class_id INTEGER,
	course_name_snapshot VARCHAR(128),
	class_name_snapshot VARCHAR(128),
	classroom_snapshot VARCHAR(128),
	teacher_name_snapshot VARCHAR(128),
	require_photo_snapshot BOOLEAN DEFAULT 0 NOT NULL,
	expected_count_snapshot INTEGER DEFAULT 0 NOT NULL,
	expected_count_current INTEGER DEFAULT 0 NOT NULL,
	roster_version INTEGER DEFAULT 1 NOT NULL,
	canceled_at DATETIME,
	canceled_by INTEGER,
	cancel_reason VARCHAR(512),
	lock_version INTEGER DEFAULT 0 NOT NULL,
	college_id INTEGER,
	ownership_version INTEGER DEFAULT 1 NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_inspection_task PRIMARY KEY (id),
	CONSTRAINT ck_inspection_task_ck_inspection_task_type CHECK (inspection_type IN ('COURSE','MORNING_STUDY','EVENING_STUDY')),
	CONSTRAINT ck_inspection_task_ck_inspection_task_period_range CHECK (end_period >= start_period),
	CONSTRAINT ck_inspection_task_ck_inspection_task_expected_current CHECK (expected_count_current >= 0),
	CONSTRAINT uq_inspection_task_task_key UNIQUE (task_key),
	CONSTRAINT fk_inspection_task_semester_id_semester FOREIGN KEY(semester_id) REFERENCES semester (id) ON DELETE RESTRICT,
	CONSTRAINT fk_inspection_task_course_schedule_id_course_schedule FOREIGN KEY(course_schedule_id) REFERENCES course_schedule (id) ON DELETE RESTRICT,
	CONSTRAINT fk_inspection_task_teaching_class_id_teaching_class FOREIGN KEY(teaching_class_id) REFERENCES teaching_class (id) ON DELETE RESTRICT,
	CONSTRAINT fk_inspection_task_administrative_class_id_administrative_class FOREIGN KEY(administrative_class_id) REFERENCES administrative_class (id) ON DELETE RESTRICT,
	CONSTRAINT fk_inspection_task_canceled_by_user_account FOREIGN KEY(canceled_by) REFERENCES user_account (id) ON DELETE SET NULL,
	CONSTRAINT fk_inspection_task_college_id_college FOREIGN KEY(college_id) REFERENCES college (id) ON DELETE RESTRICT
);
CREATE TABLE objection (
	id INTEGER NOT NULL,
	attendance_record_id INTEGER NOT NULL,
	student_id INTEGER NOT NULL,
	base_attendance_version INTEGER NOT NULL,
	reason VARCHAR(512) NOT NULL,
	desired_type VARCHAR(16) NOT NULL,
	initial_status VARCHAR(16) DEFAULT 'PENDING' NOT NULL,
	initial_reviewed_by INTEGER,
	initial_reviewed_at DATETIME,
	initial_comment VARCHAR(512),
	final_status VARCHAR(16) DEFAULT 'PENDING' NOT NULL,
	final_reviewed_by INTEGER,
	final_reviewed_at DATETIME,
	final_comment VARCHAR(512),
	final_attendance_type VARCHAR(16),
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_objection PRIMARY KEY (id),
	CONSTRAINT ck_objection_ck_objection_desired_type CHECK (desired_type IN ('NORMAL','LEAVE','LATE','ABSENT')),
	CONSTRAINT ck_objection_ck_objection_final_attendance_type CHECK (final_attendance_type IS NULL OR final_attendance_type IN ('NORMAL','LEAVE','LATE','ABSENT')),
	CONSTRAINT ck_objection_ck_objection_initial_status CHECK (initial_status IN ('PENDING','PASSED','REJECTED')),
	CONSTRAINT ck_objection_ck_objection_final_status CHECK (final_status IN ('PENDING','APPROVED','REJECTED')),
	CONSTRAINT fk_objection_attendance_record_id_attendance_record FOREIGN KEY(attendance_record_id) REFERENCES attendance_record (id) ON DELETE CASCADE,
	CONSTRAINT fk_objection_student_id_student FOREIGN KEY(student_id) REFERENCES student (id) ON DELETE RESTRICT,
	CONSTRAINT fk_objection_initial_reviewed_by_user_account FOREIGN KEY(initial_reviewed_by) REFERENCES user_account (id) ON DELETE SET NULL,
	CONSTRAINT fk_objection_final_reviewed_by_user_account FOREIGN KEY(final_reviewed_by) REFERENCES user_account (id) ON DELETE SET NULL
);
CREATE TABLE objection_file (
	objection_id INTEGER NOT NULL,
	file_id INTEGER NOT NULL,
	CONSTRAINT pk_objection_file PRIMARY KEY (objection_id, file_id),
	CONSTRAINT fk_objection_file_objection_id_objection FOREIGN KEY(objection_id) REFERENCES objection (id) ON DELETE CASCADE,
	CONSTRAINT fk_objection_file_file_id_file_object FOREIGN KEY(file_id) REFERENCES file_object (id) ON DELETE RESTRICT
);
CREATE TABLE period_definition (
	id INTEGER NOT NULL,
	semester_id INTEGER NOT NULL,
	period_no INTEGER NOT NULL,
	start_time TIME,
	end_time TIME,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_period_definition PRIMARY KEY (id),
	CONSTRAINT uq_period_definition_semester_no UNIQUE (semester_id, period_no),
	CONSTRAINT fk_period_definition_semester_id_semester FOREIGN KEY(semester_id) REFERENCES semester (id) ON DELETE RESTRICT
);
CREATE TABLE permission (
	id INTEGER NOT NULL,
	code VARCHAR(64) NOT NULL,
	name VARCHAR(128) NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_permission PRIMARY KEY (id),
	CONSTRAINT uq_permission_code UNIQUE (code)
);
CREATE TABLE report (
	id INTEGER NOT NULL,
	semester_id INTEGER NOT NULL,
	week_no INTEGER NOT NULL,
	scope VARCHAR(16) DEFAULT 'COLLEGE' NOT NULL,
	latest_version_no INTEGER DEFAULT 0 NOT NULL,
	latest_updated_at DATETIME,
	college_id INTEGER,
	ownership_version INTEGER DEFAULT 1 NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_report PRIMARY KEY (id),
	CONSTRAINT ck_report_ck_report_scope CHECK (scope IN ('COLLEGE','CLASS')),
	CONSTRAINT ck_report_ck_report_week CHECK (week_no >= 1),
	CONSTRAINT ck_report_ck_report_latest_version CHECK (latest_version_no >= 0),
	CONSTRAINT uq_report_sem_week_scope UNIQUE (semester_id, week_no, scope),
	CONSTRAINT fk_report_semester_id_semester FOREIGN KEY(semester_id) REFERENCES semester (id) ON DELETE RESTRICT,
	CONSTRAINT fk_report_college_id_college FOREIGN KEY(college_id) REFERENCES college (id) ON DELETE RESTRICT
);
CREATE TABLE report_source_revision (
	semester_id INTEGER NOT NULL,
	week_no INTEGER NOT NULL,
	revision BIGINT DEFAULT 0 NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_report_source_revision PRIMARY KEY (semester_id, week_no),
	CONSTRAINT ck_report_source_revision_ck_report_source_revision_nonneg CHECK (revision >= 0),
	CONSTRAINT ck_report_source_revision_ck_report_source_revision_week CHECK (week_no >= 1),
	CONSTRAINT fk_report_source_revision_semester_id_semester FOREIGN KEY(semester_id) REFERENCES semester (id) ON DELETE RESTRICT
);
CREATE TABLE report_version (
	id INTEGER NOT NULL,
	report_id INTEGER NOT NULL,
	version_no INTEGER NOT NULL,
	source_revision BIGINT DEFAULT 0 NOT NULL,
	rule_version INTEGER DEFAULT 1 NOT NULL,
	template_version INTEGER DEFAULT 1 NOT NULL,
	snapshot_file_id INTEGER,
	excel_file_id INTEGER,
	word_file_id INTEGER,
	status VARCHAR(16) DEFAULT 'GENERATING' NOT NULL,
	attempt_token VARCHAR(64),
	generated_by INTEGER,
	generated_at DATETIME,
	reason VARCHAR(512),
	created_at DATETIME NOT NULL,
	CONSTRAINT pk_report_version PRIMARY KEY (id),
	CONSTRAINT ck_report_version_ck_report_version_status CHECK (status IN ('GENERATING','PUBLISHED','FAILED')),
	CONSTRAINT ck_report_version_ck_report_version_source_revision CHECK (source_revision >= 0),
	CONSTRAINT ck_report_version_ck_report_version_no CHECK (version_no >= 1),
	CONSTRAINT uq_report_version_report_no UNIQUE (report_id, version_no),
	CONSTRAINT fk_report_version_report_id_report FOREIGN KEY(report_id) REFERENCES report (id) ON DELETE CASCADE,
	CONSTRAINT fk_report_version_snapshot_file_id_file_object FOREIGN KEY(snapshot_file_id) REFERENCES file_object (id) ON DELETE SET NULL,
	CONSTRAINT fk_report_version_excel_file_id_file_object FOREIGN KEY(excel_file_id) REFERENCES file_object (id) ON DELETE SET NULL,
	CONSTRAINT fk_report_version_word_file_id_file_object FOREIGN KEY(word_file_id) REFERENCES file_object (id) ON DELETE SET NULL,
	CONSTRAINT fk_report_version_generated_by_user_account FOREIGN KEY(generated_by) REFERENCES user_account (id) ON DELETE SET NULL
);
CREATE TABLE role (
	id INTEGER NOT NULL,
	code VARCHAR(64) NOT NULL,
	name VARCHAR(128) NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_role PRIMARY KEY (id),
	CONSTRAINT uq_role_code UNIQUE (code)
);
CREATE TABLE role_permission (
	role_id INTEGER NOT NULL,
	permission_id INTEGER NOT NULL,
	CONSTRAINT pk_role_permission PRIMARY KEY (role_id, permission_id),
	CONSTRAINT fk_role_permission_role_id_role FOREIGN KEY(role_id) REFERENCES role (id) ON DELETE CASCADE,
	CONSTRAINT fk_role_permission_permission_id_permission FOREIGN KEY(permission_id) REFERENCES permission (id) ON DELETE CASCADE
);
CREATE TABLE school (
	id INTEGER NOT NULL,
	code VARCHAR(32) NOT NULL,
	singleton_key INTEGER NOT NULL,
	name VARCHAR(128) NOT NULL,
	lock_version INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_school PRIMARY KEY (id),
	CONSTRAINT uq_school_singleton_key UNIQUE (singleton_key),
	CONSTRAINT ck_school_school_singleton CHECK (singleton_key = 1),
	CONSTRAINT uq_school_code UNIQUE (code)
);
CREATE TABLE scoped_grant (
	id INTEGER NOT NULL,
	college_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	actions JSON NOT NULL,
	starts_at DATETIME,
	expires_at DATETIME,
	status VARCHAR(16) NOT NULL,
	granted_by INTEGER NOT NULL,
	lock_version INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_scoped_grant PRIMARY KEY (id),
	CONSTRAINT ck_scoped_grant_scoped_grant_status CHECK (status IN ('ACTIVE','REVOKED')),
	CONSTRAINT fk_scoped_grant_college_id_college FOREIGN KEY(college_id) REFERENCES college (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scoped_grant_user_id_user_account FOREIGN KEY(user_id) REFERENCES user_account (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scoped_grant_granted_by_user_account FOREIGN KEY(granted_by) REFERENCES user_account (id) ON DELETE RESTRICT
);
CREATE TABLE semester (
	id INTEGER NOT NULL,
	code VARCHAR(32) NOT NULL,
	name VARCHAR(128) NOT NULL,
	start_date DATE NOT NULL,
	end_date DATE NOT NULL,
	first_monday DATE NOT NULL,
	total_weeks INTEGER DEFAULT 20 NOT NULL,
	status VARCHAR(16) DEFAULT 'ACTIVE' NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_semester PRIMARY KEY (id),
	CONSTRAINT ck_semester_ck_semester_status CHECK (status IN ('ACTIVE','ARCHIVED')),
	CONSTRAINT uq_semester_code UNIQUE (code)
);
CREATE TABLE student (
	id INTEGER NOT NULL,
	student_no VARCHAR(32) NOT NULL,
	name VARCHAR(128) NOT NULL,
	administrative_class_id INTEGER,
	status VARCHAR(16) DEFAULT 'ACTIVE' NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_student PRIMARY KEY (id),
	CONSTRAINT uq_student_student_no UNIQUE (student_no),
	CONSTRAINT fk_student_administrative_class_id_administrative_class FOREIGN KEY(administrative_class_id) REFERENCES administrative_class (id) ON DELETE SET NULL
);
CREATE TABLE submission_abnormal_item (
	id INTEGER NOT NULL,
	submission_id INTEGER NOT NULL,
	student_id INTEGER NOT NULL,
	attendance_type VARCHAR(16) NOT NULL,
	note VARCHAR(512),
	CONSTRAINT pk_submission_abnormal_item PRIMARY KEY (id),
	CONSTRAINT uq_submission_abnormal_item_sub_stu UNIQUE (submission_id, student_id),
	CONSTRAINT ck_submission_abnormal_item_ck_submission_abnormal_item_type CHECK (attendance_type IN ('LEAVE','LATE','ABSENT')),
	CONSTRAINT fk_submission_abnormal_item_submission_id_inspection_submission FOREIGN KEY(submission_id) REFERENCES inspection_submission (id) ON DELETE CASCADE,
	CONSTRAINT fk_submission_abnormal_item_student_id_student FOREIGN KEY(student_id) REFERENCES student (id) ON DELETE RESTRICT
);
CREATE TABLE submission_deadline_day (
	id INTEGER NOT NULL,
	semester_id INTEGER NOT NULL,
	inspection_date DATE NOT NULL,
	deadline_at DATETIME NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	updated_by INTEGER,
	reason VARCHAR(512),
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_submission_deadline_day PRIMARY KEY (id),
	CONSTRAINT uq_submission_deadline_day_sem_date UNIQUE (semester_id, inspection_date),
	CONSTRAINT ck_submission_deadline_day_ck_submission_deadline_day_version CHECK (version >= 1),
	CONSTRAINT fk_submission_deadline_day_semester_id_semester FOREIGN KEY(semester_id) REFERENCES semester (id) ON DELETE RESTRICT,
	CONSTRAINT fk_submission_deadline_day_updated_by_user_account FOREIGN KEY(updated_by) REFERENCES user_account (id) ON DELETE SET NULL
);
CREATE TABLE submission_deadline_version (
	id INTEGER NOT NULL,
	deadline_day_id INTEGER NOT NULL,
	version_no INTEGER NOT NULL,
	deadline_at DATETIME NOT NULL,
	changed_by INTEGER,
	reason VARCHAR(512),
	created_at DATETIME NOT NULL,
	CONSTRAINT pk_submission_deadline_version PRIMARY KEY (id),
	CONSTRAINT uq_submission_deadline_version_day_no UNIQUE (deadline_day_id, version_no),
	CONSTRAINT fk_submission_deadline_version_deadline_day_id_submission_deadline_day FOREIGN KEY(deadline_day_id) REFERENCES submission_deadline_day (id) ON DELETE CASCADE,
	CONSTRAINT fk_submission_deadline_version_changed_by_user_account FOREIGN KEY(changed_by) REFERENCES user_account (id) ON DELETE SET NULL
);
CREATE TABLE submission_file (
	submission_id INTEGER NOT NULL,
	file_id INTEGER NOT NULL,
	CONSTRAINT pk_submission_file PRIMARY KEY (submission_id, file_id),
	CONSTRAINT fk_submission_file_submission_id_inspection_submission FOREIGN KEY(submission_id) REFERENCES inspection_submission (id) ON DELETE CASCADE,
	CONSTRAINT fk_submission_file_file_id_file_object FOREIGN KEY(file_id) REFERENCES file_object (id) ON DELETE RESTRICT
);
CREATE TABLE task_deadline_assessment (
	id INTEGER NOT NULL,
	task_id INTEGER NOT NULL,
	deadline_version_id INTEGER,
	deadline_at_snapshot DATETIME NOT NULL,
	assignee_user_id_snapshot INTEGER,
	result VARCHAR(24) NOT NULL,
	evaluated_at DATETIME NOT NULL,
	created_at DATETIME NOT NULL,
	CONSTRAINT pk_task_deadline_assessment PRIMARY KEY (id),
	CONSTRAINT ck_task_deadline_assessment_ck_task_deadline_assessment_result CHECK (result IN ('VALID_SUBMISSION','OVERDUE_UNEXECUTED','CANCELED')),
	CONSTRAINT uq_task_deadline_assessment_task_id UNIQUE (task_id),
	CONSTRAINT fk_task_deadline_assessment_task_id_inspection_task FOREIGN KEY(task_id) REFERENCES inspection_task (id) ON DELETE CASCADE,
	CONSTRAINT fk_task_deadline_assessment_deadline_version_id_submission_deadline_version FOREIGN KEY(deadline_version_id) REFERENCES submission_deadline_version (id) ON DELETE RESTRICT,
	CONSTRAINT fk_task_deadline_assessment_assignee_user_id_snapshot_user_account FOREIGN KEY(assignee_user_id_snapshot) REFERENCES user_account (id) ON DELETE SET NULL
);
CREATE TABLE task_roster_member (
	id INTEGER NOT NULL,
	task_id INTEGER NOT NULL,
	roster_version INTEGER NOT NULL,
	student_id INTEGER NOT NULL,
	student_no VARCHAR(32) NOT NULL,
	name VARCHAR(128) NOT NULL,
	class_name_snapshot VARCHAR(128),
	grade_year_snapshot INTEGER,
	CONSTRAINT pk_task_roster_member PRIMARY KEY (id),
	CONSTRAINT uq_task_roster_member_task_ver_stu UNIQUE (task_id, roster_version, student_id),
	CONSTRAINT fk_task_roster_member_task_id_inspection_task FOREIGN KEY(task_id) REFERENCES inspection_task (id) ON DELETE CASCADE,
	CONSTRAINT fk_task_roster_member_student_id_student FOREIGN KEY(student_id) REFERENCES student (id) ON DELETE RESTRICT
);
CREATE TABLE task_roster_version (
	id INTEGER NOT NULL,
	task_id INTEGER NOT NULL,
	version_no INTEGER NOT NULL,
	reason VARCHAR(512),
	created_by INTEGER,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_task_roster_version PRIMARY KEY (id),
	CONSTRAINT uq_task_roster_version_task_no UNIQUE (task_id, version_no),
	CONSTRAINT fk_task_roster_version_task_id_inspection_task FOREIGN KEY(task_id) REFERENCES inspection_task (id) ON DELETE CASCADE,
	CONSTRAINT fk_task_roster_version_created_by_user_account FOREIGN KEY(created_by) REFERENCES user_account (id) ON DELETE SET NULL
);
CREATE TABLE teaching_class (
	id INTEGER NOT NULL,
	semester_id INTEGER NOT NULL,
	course_id INTEGER NOT NULL,
	class_code VARCHAR(64),
	class_name VARCHAR(128) NOT NULL,
	teacher_name VARCHAR(128),
	status VARCHAR(16) DEFAULT 'ACTIVE' NOT NULL,
	college_id INTEGER,
	ownership_version INTEGER DEFAULT 1 NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_teaching_class PRIMARY KEY (id),
	CONSTRAINT uq_teaching_class_key UNIQUE (semester_id, course_id, class_code),
	CONSTRAINT fk_teaching_class_semester_id_semester FOREIGN KEY(semester_id) REFERENCES semester (id) ON DELETE RESTRICT,
	CONSTRAINT fk_teaching_class_course_id_course FOREIGN KEY(course_id) REFERENCES course (id) ON DELETE RESTRICT,
	CONSTRAINT fk_teaching_class_college_id_college FOREIGN KEY(college_id) REFERENCES college (id) ON DELETE RESTRICT
);
CREATE TABLE teaching_class_student (
	teaching_class_id INTEGER NOT NULL,
	student_id INTEGER NOT NULL,
	CONSTRAINT pk_teaching_class_student PRIMARY KEY (teaching_class_id, student_id),
	CONSTRAINT fk_teaching_class_student_teaching_class_id_teaching_class FOREIGN KEY(teaching_class_id) REFERENCES teaching_class (id) ON DELETE CASCADE,
	CONSTRAINT fk_teaching_class_student_student_id_student FOREIGN KEY(student_id) REFERENCES student (id) ON DELETE CASCADE
);
CREATE TABLE user_account (
	id INTEGER NOT NULL,
	username VARCHAR(64),
	password_hash VARCHAR(255),
	student_id INTEGER,
	display_name VARCHAR(128) NOT NULL,
	status VARCHAR(16) DEFAULT 'ACTIVE' NOT NULL,
	failed_login_count INTEGER DEFAULT 0 NOT NULL,
	locked_until DATETIME,
	lock_version INTEGER DEFAULT 0 NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_user_account PRIMARY KEY (id),
	CONSTRAINT uq_user_account_username UNIQUE (username),
	CONSTRAINT uq_user_account_student_id UNIQUE (student_id),
	CONSTRAINT fk_user_account_student_id_student FOREIGN KEY(student_id) REFERENCES student (id) ON DELETE RESTRICT
);
CREATE TABLE user_permission (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	permission_id INTEGER NOT NULL,
	granted_by INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	CONSTRAINT pk_user_permission PRIMARY KEY (id),
	CONSTRAINT uq_user_permission_user_id UNIQUE (user_id, permission_id),
	CONSTRAINT fk_user_permission_user_id_user_account FOREIGN KEY(user_id) REFERENCES user_account (id) ON DELETE CASCADE,
	CONSTRAINT fk_user_permission_permission_id_permission FOREIGN KEY(permission_id) REFERENCES permission (id) ON DELETE CASCADE,
	CONSTRAINT fk_user_permission_granted_by_user_account FOREIGN KEY(granted_by) REFERENCES user_account (id) ON DELETE RESTRICT
);
CREATE TABLE user_role (
	user_id INTEGER NOT NULL,
	role_id INTEGER NOT NULL,
	CONSTRAINT pk_user_role PRIMARY KEY (user_id, role_id),
	CONSTRAINT fk_user_role_user_id_user_account FOREIGN KEY(user_id) REFERENCES user_account (id) ON DELETE CASCADE,
	CONSTRAINT fk_user_role_role_id_role FOREIGN KEY(role_id) REFERENCES role (id) ON DELETE CASCADE
);
CREATE TABLE volunteer_day_lock (
	volunteer_user_id INTEGER NOT NULL,
	inspection_date DATE NOT NULL,
	CONSTRAINT pk_volunteer_day_lock PRIMARY KEY (volunteer_user_id, inspection_date),
	CONSTRAINT fk_volunteer_day_lock_volunteer_user_id_user_account FOREIGN KEY(volunteer_user_id) REFERENCES user_account (id) ON DELETE CASCADE
);
CREATE TABLE volunteer_group (
	id INTEGER NOT NULL,
	college_id INTEGER NOT NULL,
	name VARCHAR(128) NOT NULL,
	normalized_name VARCHAR(128) NOT NULL,
	owner_user_id INTEGER NOT NULL,
	starts_on DATE,
	ends_on DATE,
	status VARCHAR(16) NOT NULL,
	config_version INTEGER NOT NULL,
	lock_version INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_volunteer_group PRIMARY KEY (id),
	CONSTRAINT uq_volunteer_group_college_id UNIQUE (college_id, id),
	CONSTRAINT uq_volunteer_group_name UNIQUE (college_id, normalized_name),
	CONSTRAINT ck_volunteer_group_volunteer_group_status CHECK (status IN ('DRAFT','ACTIVE','INACTIVE')),
	CONSTRAINT fk_volunteer_group_college_id_college FOREIGN KEY(college_id) REFERENCES college (id) ON DELETE RESTRICT,
	CONSTRAINT fk_volunteer_group_owner_user_id_user_account FOREIGN KEY(owner_user_id) REFERENCES user_account (id) ON DELETE RESTRICT
);
CREATE TABLE volunteer_qualification (
	id INTEGER NOT NULL,
	semester_id INTEGER NOT NULL,
	student_id INTEGER NOT NULL,
	enabled BOOLEAN DEFAULT 1 NOT NULL,
	created_by INTEGER,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	CONSTRAINT pk_volunteer_qualification PRIMARY KEY (id),
	CONSTRAINT uq_volunteer_qualification_sem_stu UNIQUE (semester_id, student_id),
	CONSTRAINT fk_volunteer_qualification_semester_id_semester FOREIGN KEY(semester_id) REFERENCES semester (id) ON DELETE RESTRICT,
	CONSTRAINT fk_volunteer_qualification_student_id_student FOREIGN KEY(student_id) REFERENCES student (id) ON DELETE RESTRICT,
	CONSTRAINT fk_volunteer_qualification_created_by_user_account FOREIGN KEY(created_by) REFERENCES user_account (id) ON DELETE SET NULL
);
CREATE TABLE wechat_identity (
	id INTEGER NOT NULL,
	appid VARCHAR(64) NOT NULL,
	openid VARCHAR(128) NOT NULL,
	user_id INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	CONSTRAINT pk_wechat_identity PRIMARY KEY (id),
	CONSTRAINT uq_wechat_identity_appid_openid UNIQUE (appid, openid),
	CONSTRAINT fk_wechat_identity_user_id_user_account FOREIGN KEY(user_id) REFERENCES user_account (id) ON DELETE RESTRICT
);
CREATE INDEX ix_period_definition_semester_id ON period_definition (semester_id);
CREATE INDEX ix_calendar_override_semester_id ON calendar_override (semester_id);
CREATE INDEX ix_administrative_class_college_id ON administrative_class (college_id);
CREATE INDEX ix_teaching_class_course_id ON teaching_class (course_id);
CREATE INDEX ix_teaching_class_college_id ON teaching_class (college_id);
CREATE INDEX ix_teaching_class_semester_id ON teaching_class (semester_id);
CREATE INDEX ix_report_semester_id ON report (semester_id);
CREATE INDEX ix_report_college_id ON report (college_id);
CREATE INDEX ix_course_schedule_college_id ON course_schedule (college_id);
CREATE INDEX ix_course_schedule_teaching_class_id ON course_schedule (teaching_class_id);
CREATE INDEX ix_course_schedule_semester_id ON course_schedule (semester_id);
CREATE INDEX ix_course_schedule_week_schedule_id ON course_schedule_week (schedule_id);
CREATE INDEX ix_identity_binding_token_token_hash ON identity_binding_token (token_hash);
CREATE INDEX ix_volunteer_qualification_student_id ON volunteer_qualification (student_id);
CREATE INDEX ix_volunteer_qualification_semester_id ON volunteer_qualification (semester_id);
CREATE INDEX ix_audit_log_actor_user_id ON audit_log (actor_user_id);
CREATE INDEX ix_audit_log_created_at_id ON audit_log (created_at, id);
CREATE INDEX ix_file_object_uploader_user_id ON file_object (uploader_user_id);
CREATE INDEX ix_file_object_category ON file_object (category);
CREATE INDEX ix_file_object_status ON file_object (status);
CREATE INDEX ix_auth_session_refresh_family_id ON auth_session (refresh_family_id);
CREATE INDEX ix_auth_session_user_id ON auth_session (user_id);
CREATE INDEX ix_auth_session_refresh_token_hash ON auth_session (refresh_token_hash);
CREATE INDEX ix_import_batch_college_id ON import_batch (college_id);
CREATE INDEX ix_inspection_task_college_id ON inspection_task (college_id);
CREATE INDEX ix_inspection_task_semester_id ON inspection_task (semester_id);
CREATE INDEX ix_inspection_task_inspection_date ON inspection_task (inspection_date);
CREATE INDEX ix_submission_deadline_day_semester_id ON submission_deadline_day (semester_id);
CREATE INDEX ix_scoped_grant_college_id ON scoped_grant (college_id);
CREATE INDEX ix_scoped_grant_user_id ON scoped_grant (user_id);
CREATE INDEX ix_task_roster_version_task_id ON task_roster_version (task_id);
CREATE INDEX ix_task_roster_member_task_id ON task_roster_member (task_id);
CREATE INDEX ix_task_roster_member_student_id ON task_roster_member (student_id);
CREATE INDEX ix_submission_deadline_version_deadline_day_id ON submission_deadline_version (deadline_day_id);
CREATE INDEX ix_inspection_assignment_task_id ON inspection_assignment (task_id);
CREATE INDEX ix_inspection_assignment_volunteer_user_id ON inspection_assignment (volunteer_user_id);
CREATE INDEX ix_report_version_report_id ON report_version (report_id);
CREATE INDEX ix_report_version_status ON report_version (status);
CREATE INDEX ix_report_version_generated_by ON report_version (generated_by);
CREATE INDEX ix_assignment_change_request_assignment_id ON assignment_change_request (assignment_id);
CREATE INDEX ix_assignment_change_request_request_user_id ON assignment_change_request (request_user_id);
CREATE INDEX ix_inspection_submission_task_id ON inspection_submission (task_id);
CREATE INDEX ix_inspection_submission_volunteer_user_id ON inspection_submission (volunteer_user_id);
CREATE INDEX ix_inspection_submission_review_status ON inspection_submission (review_status);
CREATE INDEX ix_submission_abnormal_item_student_id ON submission_abnormal_item (student_id);
CREATE INDEX ix_submission_abnormal_item_submission_id ON submission_abnormal_item (submission_id);
CREATE INDEX ix_attendance_record_student_id ON attendance_record (student_id);
CREATE INDEX ix_attendance_record_task_id ON attendance_record (task_id);
CREATE INDEX ix_attendance_record_version_attendance_record_id ON attendance_record_version (attendance_record_id);
CREATE INDEX ix_objection_attendance_record_id ON objection (attendance_record_id);
CREATE INDEX ix_objection_attendance_final_status ON objection (attendance_record_id, final_status);
CREATE INDEX ix_objection_student_id ON objection (student_id);
COMMIT;
