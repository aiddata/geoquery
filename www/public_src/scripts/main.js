angular.module('aiddataDET', ['ui.router', 'ui.bootstrap', 'angucomplete-alt', 'ngMaterial', 'rzModule'])
.config(function($stateProvider, $urlRouterProvider, $mdThemingProvider) {

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
      boundaries: function($log, $state, queryFactory) {
        $log.warn('resolve boundaries');
        return queryFactory.getBoundaries();
      },
      datasets: function($log, $q, $state, $stateParams, queryFactory) {
        $log.warn('resolve datasets');
        return queryFactory.getDatasets($stateParams.boundary)
          .then(function(data) { return data; })
          .catch(function() { $state.go('map'); });
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
      filters: function(queryFactory, $log) {
        $log.warn('resolve filters');
        queryFactory.clearOptions();
        queryFactory.clearFilters();
        return queryFactory.filters;
      },
      filterOptions: function($log, $stateParams, queryFactory) {
        $log.warn('resolve filterOptions');
        return queryFactory.setDataset($stateParams.dataset);
      }
    },
    onEnter: function($log) {
      $log.debug('Entering search.filters');
    },
    onExit: function($log) {
      $log.debug('Exiting search.filters');
    }
  })
  .state('search.options', {
    url: '/external/:dataset',
    templateUrl: 'views/components/search.options.html',
    controller: 'OptionsCtrl',
    resolve: {
      options: function(queryFactory, $log) {
        $log.warn('resolve options');
        queryFactory.clearOptions();
        queryFactory.clearFilters();
        return queryFactory.filters;
      },
      filterOptions: function($log, $state, $stateParams, queryFactory) {
        $log.warn('resolve filterOptions');
        return queryFactory.setDataset($stateParams.dataset);
      }
    },
    onEnter: function($log) {
      $log.debug('Entering search.options');
    },
    onExit: function($log) {
      $log.debug('Exiting search.options');
    }
  })
  .state('search.filters', {
    url: '/release/:dataset',
    templateUrl: 'views/components/search.filters.html',
    controller: 'FiltersCtrl'
  })
  .state('search.options', {
    url: '/external/:dataset',
    templateUrl: 'views/components/search.options.html',
    controller: 'OptionsCtrl'
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
