from models.user import UserModel


def build_users():
    users = [
        UserModel(user_name="Test1", email="user1@example.com", district="capital"),
        UserModel(user_name="Test2", email="user2@example.com", district="southern"),
        UserModel(user_name="Test3", email="user3@example.com", district="muharraq"),
        UserModel(user_name="Test4", email="user4@example.com", district="northern"),
    ]
    for user in users:
        user.set_password("123")
    return users


user_list = build_users()
