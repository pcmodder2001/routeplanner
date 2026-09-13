# Seed always-carry van kit product list

from django.db import migrations

# (sort_order, product_code, name)
VAN_KIT_SEED = [
    (10, '088096', 'Double NTE VDSL'),
    (20, '004624', 'Jelly crimps'),
    (30, '211343', 'Yellow double sided tape'),
    (40, '007852', 'Black boxes'),
    (50, '048884', 'Jumper wire Blue&yellow'),
    (60, '127865', 'Clear sealant'),
    (70, '072492', 'Black cable ties'),
    (80, '076061', 'Pair proves tags'),
    (90, '129408', 'Black fine point marker'),
    (100, '129392', 'Gold paint pen'),
    (110, '097501', 'Internal cable white'),
    (120, '062778', '5 core drop wire black'),
    (130, '079617', 'White galvanised staples'),
    (140, '061022', 'Black cleats'),
    (150, '061020', 'White cleats'),
    (160, '061021', 'Brown cleats'),
    (170, '016443', 'Drop wire clamp (Curly Wurly)'),
    (180, '211456', 'Screws'),
    (190, '211457', 'Screws'),
    (200, '038271', 'AJC (black external)'),
    (210, '075995', 'Insulation tape Black'),
    (220, '016445', 'Small eyebolt'),
    (230, '011114', 'Bracket 22'),
    (240, '016264', 'Bracket 32'),
    (250, '009561', 'Bracket 44'),
    (260, '072256', 'BT66 AGC'),
    (270, '070882-RED', 'Raw plugs'),
    (280, '070881-YELLOW', 'Raw plugs'),
    (290, '545509', 'Raw plugs'),
    (300, '068269', 'Pole tag pre climb labels'),
    (310, '070864', 'Pole climb pins'),
    (320, '005381', 'A1024 labels'),
    (330, '026946', 'A108 no access cards'),
    (340, '093976', 'Door stay hinge'),
    (350, 'BLUE-082606', 'Toolless strip card'),
    (360, 'GREEN-083035', 'Toolless strip card'),
    (370, '072180', 'Grey capping 25'),
    (380, '016442', 'Eye bolt large'),
    (390, '092681', 'Spray Dewatering AC90'),
    (400, '088095', 'ADSL NTE'),
]


def seed_van_kit(apps, schema_editor):
    VanKitItem = apps.get_model('planner', 'VanKitItem')
    for sort_order, code, name in VAN_KIT_SEED:
        existing = VanKitItem.objects.filter(product_code__iexact=code).first()
        if existing:
            # Keep ordered state; refresh name/order if blank list was already there
            if existing.name != name or existing.sort_order != sort_order:
                existing.name = name
                existing.sort_order = sort_order
                existing.save(update_fields=['name', 'sort_order'])
            continue
        VanKitItem.objects.create(
            product_code=code,
            name=name,
            sort_order=sort_order,
        )


def unseed_van_kit(apps, schema_editor):
    VanKitItem = apps.get_model('planner', 'VanKitItem')
    codes = [c for _, c, _ in VAN_KIT_SEED]
    VanKitItem.objects.filter(product_code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('planner', '0006_van_kit_item'),
    ]

    operations = [
        migrations.RunPython(seed_van_kit, unseed_van_kit),
    ]
