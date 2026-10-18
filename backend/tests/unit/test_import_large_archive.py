from io import BytesIO
from zipfile import ZipFile

from app.modules.importer.zip_preview import expand_zip


def test_college_archive_accepts_more_than_twenty_tables():
    content = BytesIO()
    with ZipFile(content, 'w') as archive:
        for i in range(471):
            archive.writestr(f'课表/{i}.xls', b'fixture')
    assert len(expand_zip(content.getvalue())) == 471


def test_selected_batch_does_not_decompress_other_members(monkeypatch):
    content = BytesIO()
    with ZipFile(content, 'w') as archive:
        for i in range(471):
            archive.writestr(f'{i}.xls', b'fixture')
    opened = []
    original = ZipFile.open

    def track(self, member, *args, **kwargs):
        opened.append(member.filename)
        return original(self, member, *args, **kwargs)

    monkeypatch.setattr(ZipFile, 'open', track)
    assert len(expand_zip(content.getvalue(), selected_names=['1.xls', '2.xls'])) == 2
    assert opened == ['1.xls', '2.xls']
