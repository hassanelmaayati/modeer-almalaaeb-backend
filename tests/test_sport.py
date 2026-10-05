from tests.lib import api


def test_sports_are_exact_isolated_fixtures_and_missing_id_is_404(client,factory):
    first=factory.sport('Swimming',formats=[{'key':'four','capacity':4}])
    second=factory.sport('Football')
    assert [(item['id'],item['name']) for item in api(client,'GET','/sports')] == [(first['id'],'Swimming'),(second['id'],'Football')]
    assert api(client,'GET',f"/sports/{first['id']}")['name']=='Swimming'
    # The formats are exposed so clients can offer a format dropdown instead of a free capacity
    assert api(client,'GET',f"/sports/{first['id']}")['formats']==[{'key':'four','capacity':4}]
    assert api(client,'GET',f"/sports/{second['id']}")['formats'] is None
    api(client,'GET','/sports/987654',expected=404)
