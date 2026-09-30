"""验证运行账号不能改写审计或进行 DDL；失败测试均没有业务数据写入。"""
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.core.database import get_engine

with get_engine().connect() as connection:
    for statement in ('UPDATE audit_log SET id=id WHERE 1=0',
                      'CREATE TABLE course_management_permission_probe (id INT)'):
        try:
            connection.execute(text(statement))
        except DBAPIError as error:
            assert error.orig.args[0] == 1142, type(error.orig).__name__
            connection.rollback()
        else:
            raise RuntimeError('Runtime account unexpectedly has restricted privilege')
print('Runtime audit UPDATE and CREATE TABLE both denied (1142)')
