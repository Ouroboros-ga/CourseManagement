"""有界的确认集合：复用解析与写入算法，统一校验后只在末尾提交一次。"""

import hashlib
import json

from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import AppError, ConflictError, ErrorCode, NotFoundError
from app.modules.importer.confirmation_diff import changes_for
from app.modules.importer.limits import MAX_BATCH_FILES
from app.modules.importer.service import ImporterService


def _schedule_conflict_message(after, old, source):
    weeks = ",".join(str(w) for w in sorted(set(after["weeks"]) & set(old["weeks"])))
    start = max(after["start_period"], old["start_period"])
    end = min(after["end_period"], old["end_period"])
    return (
        f"同一教学班课表时间冲突：{after.get('course_name') or after.get('course_code')}，"
        f"第{weeks}周，星期{after['weekday']}，节次{start}—{end}；"
        f"与“{source['filename']}”第{source.get('row') or '?'}行重叠，"
        "请核对周次、地点和教师"
    )


class ImportConfirmationSet:
    MAX_FILES = MAX_BATCH_FILES

    def __init__(self, service):
        self.service = service
        self.db = service._session

    def _load(self, ids):
        if (
            not 1 <= len(ids) <= self.MAX_FILES
            or len(set(ids)) != len(ids)
            or any(not 0 < value < 2**63 for value in ids)
        ):
            raise AppError(ErrorCode.VALIDATION_ERROR, "一次请选择 1—100 个不同的预览文件", 422)
        batches = []
        for bid in sorted(ids):
            batch = self.service._repo.get_for_update(bid)
            if batch is None:
                raise NotFoundError("文件预览不在当前学院")
            self.service._require_composite(self.service.actor.id, batch.target)
            batches.append(batch)
        semesters = {b.semester_id for b in batches if b.semester_id is not None}
        for batch in batches:
            if batch.target == "roster":
                teaching = self.service._academic.get_teaching_class(batch.teaching_class_id)
                if teaching is None:
                    raise NotFoundError("目标教学班不存在或不可见")
                semesters.add(teaching.semester_id)
        if len(semesters) > 1:
            raise ConflictError(message="一次确认不能混合多个学期")
        has_semester = any(b.semester_id is not None for b in batches)
        has_no_semester = any(
            b.semester_id is None and (b.payload_json or {}).get("import_type") == "faculty_staff"
            for b in batches
        )
        if has_semester and has_no_semester:
            raise ConflictError(message="无学期资料与学期资料请分开确认")
        return batches

    def _plan(self, batches):
        source = self.service.source_revision()
        revision = hashlib.sha256(
            json.dumps(
                {
                    "actor": self.service.actor.id,
                    "college": self.service.cid,
                    "source": source,
                    "batches": [
                        [
                            b.id,
                            b.target,
                            b.semester_id,
                            b.teaching_class_id,
                            b.payload_json,
                            b.error_json,
                            str(b.expires_at),
                        ]
                        for b in batches
                    ],
                },
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        files, prepared, seen_files, keys, schedules = [], {}, set(), {}, []
        for batch in batches:
            analysis = changes_for(self.service, batch)
            issues = [{**row, "filename": batch.filename} for row in (batch.error_json or [])]
            issues.extend(analysis["issues"])
            if "person_links" in (batch.payload_json or {}):
                from app.modules.importer.person_links import plan_links

                current_links = plan_links(
                    self.service, batch.target, batch.payload_json, batch.semester_id
                )
                if current_links != batch.payload_json["person_links"]:
                    issues.append({"code": "CONFIRMATION_CONFLICT", "severity": "error",
                                   "message": "人员匹配或任职关系已变化，请重新读取资料核对"})
            if not analysis["changes"] and not issues:
                issues.append({"severity": "error", "filename": batch.filename,
                               "message": "文件中没有可核对的条目，请检查资料类型和文件内容"})
            try:
                self.service._validate_official_times(batch)
            except AppError as exc:
                issues.append(
                    {"severity": "error", "filename": batch.filename, "message": exc.message}
                )
            if batch.status != "PREVIEW" or batch.expires_at <= utcnow():
                issues.append(
                    {
                        "severity": "error",
                        "message": "预览已失效，请重新上传",
                        "filename": batch.filename,
                    }
                )
            if (batch.payload_json or {}).get("workspace_source_revision") != source:
                issues.append(
                    {
                        "severity": "error",
                        "message": "正式资料已变化，请重新上传核对",
                        "filename": batch.filename,
                    }
                )
            fingerprint = (
                batch.target,
                batch.semester_id,
                batch.teaching_class_id,
                (batch.payload_json or {}).get("source_file_sha256"),
            )
            duplicate = fingerprint[-1] and fingerprint in seen_files
            if duplicate:
                analysis["payload"]["confirmation_skip"] = True
                analysis["payload"]["skip_person_links"] = True
                for change in analysis["changes"]:
                    change["action"] = "UNCHANGED"
                # 已处理的相同来源不再次应用，但不掩盖源修订或文件自身的阻断错误。
                issues = [row for row in issues if row.get("code") != "CONFIRMATION_CONFLICT"]
            else:
                for change in analysis["changes"]:
                    if change["action"] == "UNCHANGED":
                        continue
                    key = (
                        batch.target,
                        batch.semester_id,
                        batch.teaching_class_id,
                        change["entity"],
                        change["key"],
                    )
                    value = json.dumps(change["after"], sort_keys=True, default=str)
                    # 课表按周次交集和节次区间判断，不能把单/双周或分段周次当作覆盖。
                    if change["entity"] != "schedule" and key in keys and (
                        keys[key][1] != value
                        or change["entity"] != "person_relation" and keys[key][0] != batch.id
                    ):
                        issues.append(
                            {
                                "severity": "error",
                                "filename": batch.filename,
                                "row": change["source"].get("row"),
                                "message": "多个文件修改同一条资料，请合并核对后重新上传",
                            }
                        )
                    keys[key] = (batch.id, value)
                    if change["entity"] == "schedule":
                        after = change["after"]
                        for scope, old, old_source in schedules:
                            if scope == change["schedule_scope"] and (
                                after["weekday"] == old["weekday"]
                                and set(after["weeks"]).intersection(old["weeks"])
                                and after["start_period"] <= old["end_period"]
                                and old["start_period"] <= after["end_period"]
                            ):
                                issues.append(
                                    {
                                        "code": "SCHEDULE_OVERLAP",
                                        "severity": "error",
                                        "filename": batch.filename,
                                        "row": change["source"].get("row"),
                                        "message": _schedule_conflict_message(
                                            after, old, old_source),
                                    }
                                )
                        schedules.append((change["schedule_scope"], after, change["source"]))
            seen_files.add(fingerprint)
            prepared[batch.id] = analysis["payload"]
            files.append(
                {
                    "id": str(batch.id),
                    "filename": batch.filename,
                    "target": (batch.payload_json or {}).get("import_type") or batch.target,
                    "changes": analysis["changes"],
                    "issues": issues,
                    "summary": batch.summary_json or {},
                }
            )
        rows = sum(len(file["changes"]) for file in files)
        if rows > get_settings().import_max_rows:
            raise AppError(ErrorCode.VALIDATION_ERROR, "确认集合超过导入条目上限，请拆成多批", 422)
        return {
            "revision": revision,
            "batch_ids": [str(b.id) for b in batches],
            "files": files,
            "can_confirm": not any(
                i.get("severity") == "error" for f in files for i in f["issues"]
            ),
            "limits": {"max_files": self.MAX_FILES, "max_changes": get_settings().import_max_rows},
            "impact_note": (
                "未出现的名单行不删除。任务按现有名单与未来影响规则处理；"
                "导入不等于发布，也不会覆盖个人课表。"
            ),
        }, prepared

    def preview(self, ids):
        with self.service.operation("import.execute"):
            batches = self._load(ids)
            plan, _ = self._plan(batches)
            return plan

    def confirm(self, ids, revision, request_id):
        with self.service.operation("import.execute"):
            batches = self._load(ids)
            if all(b.status == "CONFIRMED" for b in batches):
                if all(
                    (b.payload_json or {}).get("confirmation_set_revision") == revision
                    and (b.payload_json or {}).get("confirmation_set_ids") == sorted(ids)
                    for b in batches
                ):
                    return self._result(batches)
                raise ConflictError(message="已确认文件不属于本次确认集合")
            if any(b.status != "PREVIEW" or b.expires_at <= utcnow() for b in batches):
                raise ConflictError(message="预览已过期或状态已变化，请重新上传核对")
            plan, prepared = self._plan(batches)
            if plan["revision"] != revision:
                raise ConflictError(ErrorCode.VERSION_CONFLICT, "资料或选择集合已变化，请重新核对")
            if not plan["can_confirm"]:
                if any(
                    i.get("code") == "CONFIRMATION_CONFLICT"
                    for f in plan["files"]
                    for i in f["issues"]
                ):
                    raise ConflictError(
                        ErrorCode.VERSION_CONFLICT, "资料已发生变化，请重新核对上传"
                    )
                raise AppError(ErrorCode.VALIDATION_ERROR, "存在阻断问题，整批未保存", 422)
            try:
                for batch in batches:
                    self.service._validate_official_times(batch)
                    ImporterService.confirm(
                        self.service,
                        self.service.actor,
                        batch.id,
                        request_id,
                        commit=False,
                        prepared_payload=prepared[batch.id],
                    )
                    batch.payload_json = {
                        **(batch.payload_json or {}),
                        "confirmation_set_revision": revision,
                        "confirmation_set_ids": sorted(ids),
                    }
                self.db.commit()
            except IntegrityError as exc:
                self.db.rollback()
                raise ConflictError(
                    message="资料归属、唯一性或关联已变化，整批未保存，请重新核对文件"
                ) from exc
            return self._result(batches)

    @staticmethod
    def _result(batches):
        return {
            "status": "CONFIRMED",
            "batch_ids": [str(b.id) for b in batches],
            "files": [
                {
                    "id": str(b.id),
                    "filename": b.filename,
                    "target": (b.payload_json or {}).get("import_type") or b.target,
                    "summary": b.summary_json,
                }
                for b in batches
            ],
        }
