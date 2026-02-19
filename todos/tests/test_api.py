from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from todos.models import Todo


class TodoAPITest(APITestCase):
    def setUp(self):
        """Crea un todo de base para las pruebas que lo necesiten."""
        self.todo = Todo.objects.create(
            title="Todo inicial",
            description="Descripción de prueba",
        )

    # --- GET /api/todos/ ---
    def test_list_todos_returns_200(self):
        url = reverse("todo-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_todos_contains_created_todo(self):
        url = reverse("todo-list")
        response = self.client.get(url)
        # La respuesta paginada tiene los resultados en 'results'
        titles = [item["title"] for item in response.data["results"]]
        self.assertIn("Todo inicial", titles)

    # --- POST /api/todos/ ---
    def test_create_todo_returns_201(self):
        url = reverse("todo-list")
        data = {"title": "Nuevo todo", "description": "Nueva descripción"}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_todo_persists_in_db(self):
        url = reverse("todo-list")
        data = {"title": "Persistido", "description": ""}
        self.client.post(url, data, format="json")
        self.assertEqual(Todo.objects.count(), 2)

    def test_create_todo_without_title_returns_400(self):
        """El título es obligatorio — debe retornar 400 si falta."""
        url = reverse("todo-list")
        response = self.client.post(url, {"description": "Sin título"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # --- GET /api/todos/{id}/ ---
    def test_retrieve_todo_returns_200(self):
        url = reverse("todo-detail", args=[self.todo.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Todo inicial")

    def test_retrieve_nonexistent_todo_returns_404(self):
        url = reverse("todo-detail", args=[9999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- PUT /api/todos/{id}/ ---
    def test_update_todo_marks_as_completed(self):
        url = reverse("todo-detail", args=[self.todo.id])
        data = {"title": "Todo inicial", "description": "Descripción de prueba", "completed": True}
        response = self.client.put(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.todo.refresh_from_db()
        self.assertTrue(self.todo.completed)

    # --- PATCH /api/todos/{id}/ ---
    def test_partial_update_only_title(self):
        url = reverse("todo-detail", args=[self.todo.id])
        response = self.client.patch(url, {"title": "Título actualizado"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.todo.refresh_from_db()
        self.assertEqual(self.todo.title, "Título actualizado")

    # --- DELETE /api/todos/{id}/ ---
    def test_delete_todo_returns_204(self):
        url = reverse("todo-detail", args=[self.todo.id])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_delete_todo_removes_from_db(self):
        url = reverse("todo-detail", args=[self.todo.id])
        self.client.delete(url)
        self.assertEqual(Todo.objects.count(), 0)
