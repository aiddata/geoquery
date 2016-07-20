angular.module('aiddataDET', ['ui.router', 'ui.bootstrap', 'angucomplete-alt', 'ngMaterial', 'rzModule'])
.config(function($stateProvider, $urlRouterProvider, $mdThemingProvider) {

  // $mdThemingProvider.theme('default')
  //   .primaryPalette('blue-grey')
  //   .accentPalette('indigo', { 'default': '900' });
  //
  // $mdThemingProvider.alwaysWatchTheme(true);

  $mdThemingProvider.theme('default')
      .primaryPalette('blue-grey', {
        'default': '400', // by default use shade 400 from the pink palette for primary intentions
        'hue-1': '100', // use shade 100 for the <code>md-hue-1</code> class
        'hue-2': '600', // use shade 600 for the <code>md-hue-2</code> class
        'hue-3': 'A100' // use shade A100 for the <code>md-hue-3</code> class
      })
      .accentPalette('green', {
        'default': '500',
        'hue-1': '100', // use shade 100 for the <code>md-hue-1</code> class
        'hue-2': '600', // use shade 600 for the <code>md-hue-2</code> class
        'hue-3': 'A100' // use shade A100 for the <code>md-hue-3</code> class
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
      boundaries: function($state, queryFactory) {
        return queryFactory.getBoundaries();
      },
      datasets: function($log, $q, $state, $stateParams, queryFactory) {
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
      },
      'filters@search': {
        templateUrl: 'views/components/search.filters.html',
        controller: 'FiltersCtrl'
      },
      'options@search': {
        templateUrl: 'views/components/search.options.html',
        controller: 'OptionsCtrl'
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
