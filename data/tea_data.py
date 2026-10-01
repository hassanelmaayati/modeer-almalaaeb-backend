from models.tea import TeaModel
from models.comment import CommentModel

# We create some instances of our tea model here, which will be used in seeding.
teas_list = [
    TeaModel(name="chai", rating=4, in_stock=True, user_id=1),
    TeaModel(name="earl grey", rating=3, in_stock=False, user_id=2),
    TeaModel(name="matcha", rating=3, in_stock=True, user_id=4),
    TeaModel(name="green tea", rating=5, in_stock=True, user_id=1),
    TeaModel(name="black tea", rating=4, in_stock=True, user_id=5),
    TeaModel(name="oolong", rating=4, in_stock=False, user_id=4),
    TeaModel(name="hibiscus", rating=4, in_stock=True, user_id=3),
    TeaModel(name="peppermint", rating=5, in_stock=True, user_id=3),
    TeaModel(name="jasmine", rating=3, in_stock=True, user_id=5),
]

comments_list = [
    CommentModel(content="This is a great tea", tea_id=1, user_id=1),
    CommentModel(content="Perfect for relaxing evenings", tea_id=2, user_id=2),
    CommentModel(content="I love the vibrant green color!", tea_id=3, user_id=4),
    CommentModel(content="So refreshing and healthy!", tea_id=4, user_id=1),
    CommentModel(content="A classic choice for any time of day", tea_id=5, user_id=5),
]
