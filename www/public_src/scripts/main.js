angular.module('aiddataDET', ['ui.router', 'ui.bootstrap', 'angucomplete-alt', 'ngMaterial', 'rzModule'])
.config(function($stateProvider, $urlRouterProvider, $mdThemingProvider) {

  /* Material Design Theme Configuration */
  $mdThemingProvider.theme('default')
      .primaryPalette('blue-grey', {
        'default': '400',
        'hue-1': '100',
        'hue-2': '600',
        'hue-3': 'A100'
      })
      .accentPalette('green', {
        'default': '500',
        'hue-1': '100',
        'hue-2': '600',
        'hue-3': 'A100'
      })
      .warnPalette('deep-orange')
      .backgroundPalette('grey');

  /* Routing and State Management */

  $urlRouterProvider.otherwise('/');

  $stateProvider.state('map', {
    url: '/',
    resolve: {
      boundaries: function(queryFactory) {
        return queryFactory.getBoundaries();
      }
    },
    views: {
      '': {
        templateUrl: 'views/pages/map.html'
      },
      'geographySearch@map': {
        templateUrl: 'views/components/map.geographySearch.html',
        controller: 'GeographySearchCtrl'
      },
      'zoomControls@map': {
        templateUrl: 'views/components/map.zoomControls.html',
        controller: 'ZoomControlsCtrl'
      },
      'map@map': {
        controller: 'MapCtrl'
      }
    }
  })
  .state('search', {
    url: '/search/:boundary/:subboundary',
    resolve: {
      /* @TODO: Clean up Sychronous Resolutions */
      boundaries: function($log, $state, queryFactory) {
        return queryFactory.getBoundaries();
      },
      boundary: function($log, $stateParams, queryFactory, boundaries) {
        $log.info('boundaries:', boundaries);
        return queryFactory.setBoundary($stateParams.boundary, $stateParams.subboundary);
      },
      datasets: function($log, $state, $stateParams, queryFactory, boundary) {
        $log.info('boundary:', boundary);
        return queryFactory.getDatasets($stateParams.boundary)
          .then(function(data) { return data; })
          .catch(function() { return $state.go('map'); });
      }
    },
    views: {
      '': {
        templateUrl: 'views/pages/search.html'
      },
      'queryText@search': {
        templateUrl: 'views/components/search.queryText.html',
        controller: 'QueryTextCtrl'
      },
      'datasetSelector@search': {
        templateUrl: 'views/components/search.datasetSelector.html',
        controller: 'DatasetSelectorCtrl'
      }
    }
  })
  .state('search.filters', {
    url: '/release/:dataset',
    templateUrl: 'views/components/search.filters.html',
    controller: 'FiltersCtrl',
    resolve: {
      filters: function(queryFactory, $log, datasets) {
        $log.info('datasets:', datasets);
        queryFactory.clearOptions();
        queryFactory.clearFilters();
        return queryFactory.filters;
      },
      dataset: function($log, $stateParams, filters, queryFactory) {
        $log.info('filters:', filters);
        return queryFactory.setDataset($stateParams.dataset);
      },
      fields: function($log, $stateParams, filters, dataset, queryFactory) {
        $log.info('dataset:', dataset);
        var fields = _.chain(dataset)
          .cloneDeep()
          .get('fields')
          .value();

        queryFactory.filters = _.chain(fields)
          .filter('is_default')
          .mapKeys('field')
          .mapValues(function() { return [ 'All' ]; })
          .extend(queryFactory.filters)
          .value();

        return fields;
      },
      filterOptions: function($log, $stateParams, queryFactory, fields) {
        $log.info('fields:', fields);
        return queryFactory.updateFilters();
      },
      finally: function ($log, filterOptions) {
        $log.info('filterOptions:', filterOptions);
      }
    }
  })
  .state('search.options', {
    url: '/external/:dataset',
    templateUrl: 'views/components/search.options.html',
    controller: 'OptionsCtrl',
    resolve: {
      options: function(queryFactory, $log, datasets) {
        $log.info('datasets:', datasets);
        queryFactory.clearOptions();
        queryFactory.clearFilters();
        return queryFactory.options;
      },
      dataset: function($log, $stateParams, options, queryFactory) {
        $log.info('options:', options);
        return queryFactory.setDataset($stateParams.dataset);
      },
      filterOptions: function ($log, dataset) {
        $log.info('dataset:', dataset);
        return {};
      },
      finally: function ($log, filterOptions) {
        $log.info('filterOptions:', filterOptions);
      }
    }
  })
  .state('checkout', {
    url: '/checkout',
    templateUrl: 'views/pages/submit.html'
  })
  .state('status', {
    url: '/status',
    templateUrl: 'views/pages/status.html'
  });

});
