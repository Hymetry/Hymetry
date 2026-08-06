from django.urls import path

from apps.pages import views as pages_views
from apps.projects import (
    company_attribute_filter_views,
    company_attribute_views,
    company_segment_views,
    views,
)

app_name = 'projects'

urlpatterns = [
    path('', views.project_list, name='project_list'),
    path('<int:project_id>/intro/', views.project_intro, name='project_intro'),
    path('projects/create/', views.project_create, name='project_create'),
    path('<int:pk>/delete/', views.project_delete, name='project_delete'),
    path('<int:project_id>/pages/', pages_views.project_pages, name='project_pages'),
    path('<int:project_id>/pages/table-data/', pages_views.project_pages_table_data, name='project_pages_table_data'),
    path('<int:project_id>/pages/scatter-tooltips/', pages_views.scatter_tooltips, name='project_pages_scatter_tooltips'),
    path(
        '<int:project_id>/pages/<str:page_rule_id>/metric-dynamics/',
        pages_views.project_page_metric_dynamics,
        name='project_page_metric_dynamics',
    ),
    path(
        '<int:project_id>/pages/<str:page_rule_id>/table-data/',
        pages_views.project_page_detail_table_data,
        name='project_page_detail_table_data',
    ),
    path('<int:project_id>/pages/<str:page_rule_id>/', pages_views.project_page_detail, name='project_page_detail'),
    path('<int:project_id>/companies/', views.project_companies, name='project_companies'),
    path('<int:project_id>/companies/table-data/', views.project_companies_table_data, name='project_companies_table_data'),
    path('<int:project_id>/companies/options/', views.project_company_options, name='project_company_options'),
    path(
        '<int:project_id>/companies/<str:company_id>/metric-dynamics/',
        views.project_company_metric_dynamics,
        name='project_company_metric_dynamics',
    ),
    path(
        '<int:project_id>/companies/<str:company_id>/table-data/',
        views.project_company_detail_table_data,
        name='project_company_detail_table_data',
    ),
    path('<int:project_id>/companies/<str:company_id>/', views.project_company_detail, name='project_company_detail'),
    path('<int:project_id>/users/', views.project_users, name='project_users'),
    path('<int:project_id>/users/data/', views.project_users_data, name='project_users_data'),
    path('<int:project_id>/users/table-data/', views.project_users_table_data, name='project_users_table_data'),
    path('<int:project_id>/users/options/', views.project_user_options, name='project_user_options'),
    path(
        '<int:project_id>/analytics/variant-status/',
        views.project_analytics_variant_status,
        name='project_analytics_variant_status',
    ),
    path(
        '<int:project_id>/company-attribute-filter-preview/',
        company_attribute_filter_views.project_company_attribute_filter_preview,
        name='project_company_attribute_filter_preview',
    ),
    path(
        '<int:project_id>/company-segments/',
        company_segment_views.project_company_segments,
        name='project_company_segments',
    ),
    path(
        '<int:project_id>/company-segments/create/',
        company_segment_views.create_project_company_segment,
        name='create_project_company_segment',
    ),
    path(
        '<int:project_id>/company-segments/<str:segment_id>/update/',
        company_segment_views.update_project_company_segment,
        name='update_project_company_segment',
    ),
    path(
        '<int:project_id>/company-segments/<str:segment_id>/delete/',
        company_segment_views.delete_project_company_segment,
        name='delete_project_company_segment',
    ),
    path('<int:project_id>/users/<str:user_id>/table-data/', views.project_user_detail_table_data, name='project_user_detail_table_data'),
    path('<int:project_id>/users/<str:user_id>/', views.project_user_detail, name='project_user_detail'),
    path('<int:project_id>/settings/setup/', views.project_settings, name='project_settings'),
    path('<int:project_id>/settings/', views.project_settings, name='legacy_project_settings'),
    path(
        '<int:project_id>/settings/company-attributes/',
        company_attribute_views.project_company_attributes,
        name='project_company_attributes',
    ),
    path(
        '<int:project_id>/settings/company-attributes/table-data/',
        company_attribute_views.project_company_attributes_table_data,
        name='project_company_attributes_table_data',
    ),
    path(
        '<int:project_id>/settings/company-attributes/definitions/',
        company_attribute_views.save_project_company_attributes,
        name='save_project_company_attributes',
    ),
    path(
        '<int:project_id>/settings/company-attributes/companies/<str:company_id>/values/',
        company_attribute_views.save_project_company_attribute_values,
        name='save_project_company_attribute_values',
    ),
    path('<int:project_id>/settings/product-areas/', views.project_product_areas, name='project_product_areas'),
    path(
        '<int:project_id>/settings/product-areas/update-guidance/',
        views.update_page_structure_guidance,
        name='update_page_structure_guidance',
    ),
    path('<int:project_id>/update-name/', views.update_project_name, name='update_project_name'),
    path('<int:project_id>/update-timezone/', views.update_project_timezone, name='update_project_timezone'),
    path('<int:project_id>/update-product-url/', views.update_project_product_url, name='update_project_product_url'),
    path('<int:project_id>/update-tracking/', views.update_project_tracking, name='update_project_tracking'),
]
