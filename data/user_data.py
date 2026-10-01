from models.user import UserModel


def create_test_users():
    user1 = UserModel(username="test", email="test")
    user1.set_password("123")
    user2 = UserModel(username="emma_johnson", email="emma.johnson@email.com")
    user2.set_password("123")
    user3 = UserModel(username="fatima_ali", email="fatima.ali@mail.ae")
    user3.set_password("123")
    user4 = UserModel(username="lucas_silva", email="lucas.silva@correo.br")
    user4.set_password("123")
    user5 = UserModel(username="elena_popov", email="elena.popov@mail.ru")
    user5.set_password("123")

    return [user1, user2, user3, user4, user5]


user_list = create_test_users()
