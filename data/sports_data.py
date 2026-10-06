from models.sport import SportModel

def build_sports():
    return [
        SportModel(
            name="Football",
            formats=[
                {"key": "5v5", "capacity": 10},
                {"key": "7v7", "capacity": 14},
                {"key": "11v11", "capacity": 22},
            ],
        ),
        SportModel(
            name="Basketball",
            formats=[
                {"key": "3v3", "capacity": 6},
                {"key": "5v5", "capacity": 10},
            ],
        ),
        SportModel(
            name="Tennis",
            formats=[
                {"key": "singles", "capacity": 2},
                {"key": "doubles", "capacity": 4},
            ],
        ),
        SportModel(name="Swimming"),
        SportModel(name="Walking"),
        SportModel(name="Running"),
        SportModel(name="Cycling"),
        SportModel(
            name="Handball",
            formats=[{"key": "7v7", "capacity": 14}],
        ),
        SportModel(
            name="Padel",
            formats=[
                {"key": "singles", "capacity": 2},
                {"key": "doubles", "capacity": 4},
            ],
        ),
        SportModel(name="Kayaking"),
    ]


sports_list = build_sports()