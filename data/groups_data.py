from models.group import GroupModel


# users: the seeded users in order; sports: sport id by name (ids differ between databases)
def build_groups(users, sports):
    return [
        GroupModel(name="Group 1", sports_id=sports["Football"], owner_id=users[0].id),
        GroupModel(name="Group 2", sports_id=sports["Basketball"], owner_id=users[1].id),
        GroupModel(name="Group 3", sports_id=sports["Padel"], owner_id=users[2].id),
        GroupModel(name="Group 4", sports_id=sports["Swimming"], owner_id=users[3].id),
    ]
