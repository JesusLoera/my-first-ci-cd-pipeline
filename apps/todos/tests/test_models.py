from django.test import TestCase
from apps.todos.models import Todo


class TodoModelTest(TestCase):
    def test_create_todo_with_defaults(self):
        """Un Todo recién creado debe tener completed=False por defecto."""
        todo = Todo.objects.create(title="Aprender CI/CD")
        self.assertEqual(todo.title, "Aprender CI/CD")
        self.assertFalse(todo.completed)
        self.assertEqual(todo.description, "")

    def test_str_returns_title(self):
        """El método __str__ debe retornar el título."""
        todo = Todo.objects.create(title="Mi tarea")
        self.assertEqual(str(todo), "Mi tarea")

    def test_completed_can_be_toggled(self):
        """El campo completed puede cambiar de False a True."""
        todo = Todo.objects.create(title="Tarea pendiente")
        todo.completed = True
        todo.save()
        todo.refresh_from_db()
        self.assertTrue(todo.completed)

    def test_ordering_by_created_at_desc(self):
        """Los todos deben ordenarse del más reciente al más antiguo."""
        Todo.objects.create(title="Primero")
        Todo.objects.create(title="Segundo")
        todos = Todo.objects.all()
        self.assertEqual(todos[0].title, "Segundo")
        self.assertEqual(todos[1].title, "Primero")
