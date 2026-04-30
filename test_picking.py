from ursina import *
from ursina.physics import PhysicsEntity, physics_handler

app = Ursina(size=(400,300), borderless=False)

# Physics floor
floor = Entity(model='cube', scale=(10,1,10), collider='box', color=color.gray)
pfloor = PhysicsEntity(model='cube', scale=(10,1,10), mass=0, visible=False, collider='box')

# Spawn target
obj = PhysicsEntity(model='cube', scale=(1,1,1), y=2, mass=1.0, color=color.red, collider='box')
obj.entity.collider = 'box'
obj.entity.is_spawned_toy = True
obj.entity.parent_physics = obj

def update():
    if mouse.hovered_entity:
        print(f"Hovered: {mouse.hovered_entity}, type: {type(mouse.hovered_entity)}, has_parent_physics: {hasattr(mouse.hovered_entity, 'parent_physics')}")

def input(key):
    if key == 'left mouse down':
        if mouse.hovered_entity:
            print(f"Clicked on {mouse.hovered_entity}!")

# run physics
def fixed_update():
    physics_handler.update()

app.run()
