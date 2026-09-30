from app.modules.inspection.scheduling.location import building_cluster


def test_classroom_building_is_not_room_number():
    groups = [[13, 14, 15], [7, 8, 9], [1, 2]]
    assert building_cluster("13号楼305", groups) == "13,14,15"
    assert building_cluster("教学楼13-202", groups) == "13,14,15"
    assert building_cluster("教学楼8-阶1", groups) == "7,8,9"
    assert building_cluster("十四号楼-201", groups) == "13,14,15"
    assert building_cluster("8-305", groups) == "7,8,9"
    assert building_cluster("1305", groups) is None
    assert building_cluster("体育场", groups) is None
    assert building_cluster(None, groups) is None
    assert building_cluster("13号楼/8号楼", groups) is None
