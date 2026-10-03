from models.user import UserModel

user_list = [
    UserModel(user_name="Test1", email="user1@example.com"),
    UserModel(user_name="Test2", email="user2@example.com"),
    UserModel(user_name="Test3", email="user3@example.com"),
    UserModel(user_name="Test4", email="user4@example.com"),
]

for user in user_list:
    user.set_password("123")
