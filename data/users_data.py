from models.user import UserModel

user_list = [
    UserModel(display_name="Test One", handle="test1", email="user1@example.com"),
    UserModel(display_name="Test Two", handle="test2", email="user2@example.com"),
    UserModel(display_name="Test Three", handle="test3", email="user3@example.com"),
    UserModel(display_name="Test Four", handle="test4", email="user4@example.com"),
]

for user in user_list:
    user.set_password("123")
