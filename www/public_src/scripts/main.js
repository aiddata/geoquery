angular.module('aiddataDET', ['ui.router', 'ui.bootstrap', 'angucomplete-alt', 'ngMaterial', 'rzModule', 'ngAnimate'])
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
    params: { confirmation: { confirmed: false } },
    resolve: {
      boundaries: function(queryFactory) {
        return queryFactory.getBoundaries();
      }
    },
    onEnter: function() {
      this.params.confirmation.confirmed = false;
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
        template: '<div ng-class="{\'overlay\': showOverlay }" class="map searchMap"></div>',
        controller: 'MapCtrl'
      }
    }
  })
  .state('search', {
    url: '/search/:boundary/:subboundary',
    resolve: {
      boundary: function($log, $stateParams, queryFactory) {
        return queryFactory.getBoundaries()
          .then(function() {
            return queryFactory.setBoundary($stateParams.boundary, $stateParams.subboundary);
          });
      },
      datasets: function($log, $state, $stateParams, queryFactory, boundary) {
        return queryFactory.getDatasets(boundary.group)
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
      filters: function(queryFactory, $log) {
        return queryFactory.filters;
      },
      dataset: function($state, $stateParams, datasets, routingService) {
        return routingService.verifyDataset($state, $stateParams, datasets);
      },
      filterOptions: function($log, $stateParams, dataset, queryFactory) {
        return queryFactory.updateFilters();
      }
    }
  })
  .state('search.options', {
    url: '/external/:dataset',
    templateUrl: 'views/components/search.options.html',
    controller: 'OptionsCtrl',
    resolve: {
      options: function(queryFactory, $log, datasets) {
        return queryFactory.options;
      },
      dataset: function($state, $stateParams, datasets, routingService) {
        return routingService.verifyDataset($state, $stateParams, datasets);
      }
    }
  })
  .state('checkout', {
    url: '/checkout?mode',
    resolve: {
      query: function($state, $stateParams, $timeout, $q, $http, queryFactory) {
        console.log($stateParams);
        if ($stateParams.mode === 'test') {
          return $http.get('./tests/data/query.json')
          .then(function (results) {
            return queryFactory.setQuery(results.data);
          })
          .then(function() {
            return queryFactory.getBoundaries();
          })
          .then(function () {
            return queryFactory.setBoundary('cod_gadm28', 'cod_adm2_gadm28');
          })
          .then(function() {
            return queryFactory.getDatasets('cod_gadm28');
          }).
          then(function() {
            return queryFactory.setDataset('drc-aims_geocodedresearchrelease_level1_v1_3');
          });
        }

        var boundary = queryFactory.getBoundary(),
            subboundary = queryFactory.getSubBoundary();

        if (!boundary.boundaryId || !subboundary.name) {
          return $timeout(function() { $state.go('map'); });
        }

        if (!queryFactory.querySize()) {
          return $timeout(function() {
            $state.go('search', {
              boundary: boundary.boundaryId,
              subboundary: subboundary.name
            });
          });
        }

        return true;
      }
    },
    views: {
      '': {
        templateUrl: 'views/pages/checkout.html'
      },
      'requests@checkout': {
        templateUrl: 'views/components/checkout.requests.html',
        controller: 'RequestCtrl'
      },
      'details@checkout': {
        templateUrl: 'views/components/checkout.details.html',
        controller: 'DetailsCtrl'
      }
    }
  })
  .state('requests', {
    url: '/requests/:email',
    templateUrl: 'views/pages/requests.html',
    resolve: {
      boundaries: function($log, $state, queryFactory) {
        return queryFactory.getBoundaries();
      },
      requests: function(ajaxFactory, $stateParams) {
        // var email = decodeURIComponent(atob($stateParams.email));
        return ajaxFactory.requests('email', $stateParams.email)
          .then(function(results) { return results.data; });
      },
      datasets: function($q, requests, queryFactory) {
        var datasets = _.map(requests, function(req) {
          return queryFactory.getDatasets(req.boundary.group);
        });
        return $q.all(datasets)
        .then(function(results) {
          return _.mapKeys(results, function(d, i) { return i; });
        });
      }
    },
    controller: 'RequestsCtrl'
  })
  .state('status', {
    url: '/status/:id',
    resolve: {
      request: function(ajaxFactory, $stateParams) {
        return ajaxFactory.requests('id', $stateParams.id)
          .then(function(results) {
            return results.data[0];
          });
      },
      datasets: function(ajaxFactory, request) {
        return ajaxFactory.datasets(request.boundary.group)
          .then(function(results) { return results.data; });
      }
    },
    views: {
      '': {
        templateUrl: 'views/pages/status.html',
        controller: 'StatusCtrl'
      }
    }
  });

});
